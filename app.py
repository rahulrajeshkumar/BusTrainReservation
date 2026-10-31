import streamlit as st
from database import get_connection


st.set_page_config(
    page_title="Bus & Train Reservation System",
    page_icon="🚆",
    layout="wide"
)

st.title("🚌 Bus & Train Reservation System")
st.caption("Integrated Database Management System | Review III")

st.sidebar.title("Navigation")
page = st.sidebar.radio(
    "Select a module",
    ["Dashboard", "Search Trips", "Book a Seat", "Manage Reservations", "Payments", "Reports"]
)

if "flash_message" not in st.session_state:
    st.session_state.flash_message = None

if "flash_type" not in st.session_state:
    st.session_state.flash_type = "success"

if st.session_state.flash_message:
    message_col, dismiss_col = st.columns([0.88, 0.12])
    with message_col:
        if st.session_state.flash_type == "success":
            st.success(st.session_state.flash_message)
        elif st.session_state.flash_type == "error":
            st.error(st.session_state.flash_message)
        else:
            st.info(st.session_state.flash_message)
    with dismiss_col:
        if st.button("Dismiss", key="dismiss_flash_message"):
            st.session_state.flash_message = None
            st.session_state.flash_type = "success"
            st.rerun()


def get_count(cursor, table_name):
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    return cursor.fetchone()[0]


def get_trip_fare(connection, trip_id, fallback_fare=None):
    """Call the Oracle GET_TRIP_FARE function; use TRIP.FARE if incompatible."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT GET_TRIP_FARE(:trip_id) FROM DUAL",
                {"trip_id": trip_id}
            )
            result = cursor.fetchone()[0]
            if result is None:
                raise ValueError("GET_TRIP_FARE returned NULL.")
            return result, True
    except Exception:
        if fallback_fare is not None:
            return fallback_fare, False
        raise


def get_available_seat_count(connection, trip_id, vehicle_id):
    """Call AVAILABLE_SEATS; fall back to a reservation-aware SQL count if needed."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT AVAILABLE_SEATS(:trip_id) FROM DUAL",
                {"trip_id": trip_id}
            )
            result = cursor.fetchone()[0]
            if result is None:
                raise ValueError("AVAILABLE_SEATS returned NULL.")
            return int(result), True
    except Exception:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*)
                FROM SEAT S
                WHERE S.VEHICLE_ID = :vehicle_id
                  AND S.STATUS = 'AVAILABLE'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM RESERVATION RS
                      WHERE RS.TRIP_ID = :trip_id
                        AND RS.SEAT_ID = S.SEAT_ID
                        AND UPPER(RS.STATUS) IN ('PENDING', 'CONFIRMED')
                  )
            """, {"vehicle_id": vehicle_id, "trip_id": trip_id})
            return int(cursor.fetchone()[0]), False


def get_cursor_reservation_summary(connection):
    """Run an explicit PL/SQL cursor and return its formatted rows."""
    block = """
    DECLARE
        CURSOR reservation_cursor IS
            SELECT RS.RESERVATION_ID, P.NAME, RS.STATUS
            FROM RESERVATION RS
            JOIN PASSENGER P ON P.PASSENGER_ID = RS.PASSENGER_ID
            ORDER BY RS.RESERVATION_ID DESC;
        v_line VARCHAR2(1000);
        v_result VARCHAR2(32767) := '';
    BEGIN
        FOR rec IN reservation_cursor LOOP
            v_line := 'Reservation ' || rec.RESERVATION_ID || ' | ' ||
                      REPLACE(rec.NAME, CHR(10), ' ') || ' | ' || rec.STATUS;
            IF LENGTH(v_result) + LENGTH(v_line) + 1 > 32000 THEN
                EXIT;
            END IF;
            v_result := v_result || v_line || CHR(10);
        END LOOP;
        :result_text := v_result;
    END;
    """
    with connection.cursor() as cursor:
        result_var = cursor.var(str, size=32767)
        cursor.execute(block, result_text=result_var)
        result = result_var.getvalue()
    return result or "No reservations found."


def dashboard():
    st.header("System Dashboard")

    connection = None

    try:
        connection = get_connection()

        with connection.cursor() as cursor:
            passenger_count = get_count(cursor, "PASSENGER")
            vehicle_count = get_count(cursor, "VEHICLE")
            trip_count = get_count(cursor, "TRIP")

            cursor.execute("""
                SELECT COUNT(*)
                FROM RESERVATION
                WHERE UPPER(STATUS) = 'CONFIRMED'
            """)
            confirmed_count = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*)
                FROM RESERVATION
                WHERE UPPER(STATUS) = 'CANCELLED'
            """)
            cancelled_count = cursor.fetchone()[0]

            cursor.execute("""
                SELECT NVL(SUM(AMOUNT), 0)
                FROM PAYMENT
                WHERE UPPER(PAYMENT_STATUS) = 'PAID'
            """)
            total_payments = cursor.fetchone()[0]

        col1, col2, col3 = st.columns(3)
        col1.metric("Passengers", passenger_count)
        col2.metric("Vehicles", vehicle_count)
        col3.metric("Trips", trip_count)

        col4, col5, col6 = st.columns(3)
        col4.metric("Confirmed Reservations", confirmed_count)
        col5.metric("Cancelled Reservations", cancelled_count)
        col6.metric("Total Payments", f"₹{total_payments:,.2f}")

        st.success("Connected to Oracle Database successfully.")

    except Exception as error:
        st.error(f"Unable to load dashboard: {error}")

    finally:
        if connection:
            connection.close()


if page == "Dashboard":
    dashboard()


elif page == "Search Trips":
    st.header("🔎 Search Available Trips")

    col1, col2 = st.columns(2)

    with col1:
        source = st.text_input("Source City")

    with col2:
        destination = st.text_input("Destination City")

    search_button = st.button("Search Trips", type="primary")

    if search_button:
        connection = None

        try:
            connection = get_connection()

            with connection.cursor() as cursor:
                query = """
                    SELECT
                        T.TRIP_ID,
                        R.SOURCE,
                        R.DESTINATION,
                        V.VEHICLE_NO,
                        V.TYPE,
                        T.JOURNEY_DATE,
                        T.DEPARTURE_TIME,
                        T.FARE,
                        (
                            SELECT COUNT(*)
                            FROM SEAT S
                            WHERE S.VEHICLE_ID = T.VEHICLE_ID
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM RESERVATION RS
                                  WHERE RS.TRIP_ID = T.TRIP_ID
                                    AND RS.SEAT_ID = S.SEAT_ID
                                    AND UPPER(RS.STATUS)
                                        IN ('PENDING', 'CONFIRMED')
                              )
                        ) AS AVAILABLE_SEATS
                    FROM TRIP T
                    JOIN ROUTE R ON T.ROUTE_ID = R.ROUTE_ID
                    JOIN VEHICLE V ON T.VEHICLE_ID = V.VEHICLE_ID
                    WHERE UPPER(R.SOURCE) LIKE UPPER(:source)
                      AND UPPER(R.DESTINATION) LIKE UPPER(:destination)
                    ORDER BY T.JOURNEY_DATE, T.DEPARTURE_TIME
                """

                cursor.execute(
                    query,
                    source=f"%{source.strip()}%",
                    destination=f"%{destination.strip()}%"
                )

                rows = cursor.fetchall()

                if rows:
                    columns = [
                        "Trip ID",
                        "Source",
                        "Destination",
                        "Vehicle No",
                        "Type",
                        "Journey Date",
                        "Departure",
                        "Fare (₹)",
                        "Available Seats"
                    ]

                    results = [
                        dict(zip(columns, row))
                        for row in rows
                    ]

                    st.success(f"Found {len(rows)} trip(s).")
                    st.dataframe(
                        results,
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.warning(
                        "No trips found. Check the source and destination."
                    )

        except Exception as error:
            st.error(f"Unable to search trips: {error}")

        finally:
            if connection:
                connection.close()



elif page == "Book a Seat":
    st.header("🎫 Book a Seat")
    st.write("Select a passenger, trip, and available seat to create a reservation.")

    connection = None

    try:
        connection = get_connection()

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT PASSENGER_ID, NAME
                FROM PASSENGER
                ORDER BY NAME
            """)
            passengers = cursor.fetchall()

            cursor.execute("""
                SELECT
                    T.TRIP_ID,
                    R.SOURCE,
                    R.DESTINATION,
                    T.JOURNEY_DATE,
                    T.DEPARTURE_TIME,
                    T.FARE,
                    T.VEHICLE_ID
                FROM TRIP T
                JOIN ROUTE R ON R.ROUTE_ID = T.ROUTE_ID
                ORDER BY T.JOURNEY_DATE, T.TRIP_ID
            """)
            trips = cursor.fetchall()

        if not passengers:
            st.warning("No passengers are available.")
        elif not trips:
            st.warning("No trips are available.")
        else:
            selected_passenger = st.selectbox(
                "Select Passenger",
                passengers,
                format_func=lambda p: f"{p[0]} - {p[1]}",
                key="booking_passenger"
            )

            selected_trip = st.selectbox(
                "Select Trip",
                trips,
                format_func=lambda t: (
                    f"Trip {t[0]} | {t[1]} → {t[2]} | "
                    f"{t[3].strftime('%d-%b-%Y')} | "
                    f"{t[4]} | ₹{t[5]:,.2f}"
                ),
                key="booking_trip"
            )

            trip_id = selected_trip[0]
            vehicle_id = selected_trip[6]
            displayed_fare, fare_function_used = get_trip_fare(
                connection, trip_id, selected_trip[5]
            )
            available_count, availability_function_used = get_available_seat_count(
                connection, trip_id, vehicle_id
            )
            if not fare_function_used:
                st.warning(
                    "GET_TRIP_FARE could not be called with the expected one-argument "
                    "signature; the trip's stored fare is being used instead. "
                    "Check the function definition in Oracle."
                )
            if not availability_function_used:
                st.warning(
                    "AVAILABLE_SEATS could not be called with the expected one-argument "
                    "signature; availability is being calculated with SQL instead. "
                    "Check the function definition in Oracle."
                )
            st.caption(f"Available seats for this trip: {available_count}")

            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT S.SEAT_ID, S.SEAT_NO
                    FROM SEAT S
                    WHERE S.VEHICLE_ID = :vehicle_id
                      AND S.STATUS = 'AVAILABLE'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM RESERVATION RS
                          WHERE RS.TRIP_ID = :trip_id
                            AND RS.SEAT_ID = S.SEAT_ID
                            AND UPPER(RS.STATUS)
                                IN ('PENDING', 'CONFIRMED')
                      )
                    ORDER BY S.SEAT_NO
                """, {
                    "vehicle_id": vehicle_id,
                    "trip_id": trip_id
                })

                available_seats = cursor.fetchall()

            if not available_seats:
                st.warning(
                    "No seats are currently available for this trip."
                )
            else:
                selected_seat = st.selectbox(
                    "Select Available Seat",
                    available_seats,
                    format_func=lambda s: f"Seat {s[1]} (ID: {s[0]})",
                    key="booking_seat"
                )

                st.info(
                    f"Passenger: {selected_passenger[1]} | "
                    f"Trip: {selected_trip[1]} → {selected_trip[2]} | "
                    f"Seat: {selected_seat[1]} | "
                    f"Fare: ₹{displayed_fare:,.2f}"
                )

                if st.button("Confirm Reservation", type="primary"):
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute("""
                                SELECT NVL(MAX(RESERVATION_ID), 0) + 1
                                FROM RESERVATION
                            """)
                            reservation_id = cursor.fetchone()[0]

                            cursor.callproc(
                                "CREATE_RESERVATION",
                                [
                                    reservation_id,
                                    selected_passenger[0],
                                    trip_id,
                                    selected_seat[0]
                                ]
                            )

                        connection.commit()

                        st.session_state.flash_message = (
                            "Reservation created successfully! "
                            f"Reservation ID: {reservation_id}. "
                            "Status: PENDING. No payment has been recorded."
                        )
                        st.session_state.flash_type = "success"
                        st.rerun()

                    except Exception as booking_error:
                        connection.rollback()
                        st.session_state.flash_message = (
                            f"Booking failed: {booking_error}"
                        )
                        st.session_state.flash_type = "error"
                        st.rerun()

    except Exception as error:
        st.error(f"Unable to load booking form: {error}")

    finally:
        if connection:
            connection.close()


elif page == "Manage Reservations":
    st.header("📋 Manage Reservations")

    connection = None

    try:
        connection = get_connection()

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    RS.RESERVATION_ID,
                    P.NAME,
                    R.SOURCE,
                    R.DESTINATION,
                    T.JOURNEY_DATE,
                    S.SEAT_NO,
                    RS.BOOKING_DATE,
                    RS.STATUS
                FROM RESERVATION RS
                JOIN PASSENGER P
                    ON P.PASSENGER_ID = RS.PASSENGER_ID
                JOIN TRIP T
                    ON T.TRIP_ID = RS.TRIP_ID
                JOIN ROUTE R
                    ON R.ROUTE_ID = T.ROUTE_ID
                JOIN SEAT S
                    ON S.SEAT_ID = RS.SEAT_ID
                ORDER BY RS.RESERVATION_ID DESC
            """)

            reservations = cursor.fetchall()

        if reservations:
            status_options = [
                "ALL", "PENDING", "CONFIRMED", "CANCELLED"
            ]

            selected_status = st.selectbox(
                "Filter by Status",
                status_options,
                key="reservation_status_filter"
            )

            filtered_reservations = [
                row for row in reservations
                if selected_status == "ALL"
                or str(row[7]).upper() == selected_status
            ]

            columns = [
                "Reservation ID",
                "Passenger",
                "Source",
                "Destination",
                "Journey Date",
                "Seat",
                "Booking Date",
                "Status"
            ]

            display_rows = [
                {
                    "Reservation ID": row[0],
                    "Passenger": row[1],
                    "Source": row[2],
                    "Destination": row[3],
                    "Journey Date": row[4],
                    "Seat": row[5],
                    "Booking Date": row[6],
                    "Status": row[7]
                }
                for row in filtered_reservations
            ]

            st.dataframe(
                display_rows,
                use_container_width=True,
                hide_index=True
            )

            st.write(
                f"Showing {len(filtered_reservations)} reservation(s)."
            )

            cancellable_reservations = [
                row for row in filtered_reservations
                if str(row[7]).upper() in ("PENDING", "CONFIRMED")
            ]

            st.divider()
            st.subheader("Cancel a Reservation")

            if cancellable_reservations:
                selected_reservation = st.selectbox(
                    "Select Reservation",
                    cancellable_reservations,
                    format_func=lambda row: (
                        f"Reservation {row[0]} — {row[1]} — "
                        f"{row[2]} to {row[3]} — Seat {row[5]} "
                        f"({row[7]})"
                    ),
                    key="reservation_to_cancel"
                )

                confirm_cancel = st.checkbox(
                    "I confirm that I want to cancel this reservation.",
                    key="confirm_cancel_checkbox"
                )

                if st.button(
                    "Cancel Reservation",
                    type="primary",
                    disabled=not confirm_cancel
                ):
                    try:
                        with connection.cursor() as cursor:
                            cursor.callproc(
                                "CANCEL_RESERVATION",
                                [selected_reservation[0]]
                            )

                        connection.commit()

                        st.session_state.flash_message = (
                            f"Reservation {selected_reservation[0]} "
                            "was cancelled successfully."
                        )
                        st.session_state.flash_type = "success"
                        st.rerun()

                    except Exception as cancel_error:
                        connection.rollback()
                        st.session_state.flash_message = (
                            f"Cancellation failed: {cancel_error}"
                        )
                        st.session_state.flash_type = "error"
                        st.rerun()
            else:
                st.info(
                    "There are no pending or confirmed reservations "
                    "available to cancel under this filter."
                )

        else:
            st.info("No reservations found.")

    except Exception as error:
        st.error(f"Unable to load reservations: {error}")

    finally:
        if connection:
            connection.close()


elif page == "Payments":
    st.header("💳 Payments")
    st.caption(
        "Record a payment against an existing reservation. This records "
        "the transaction in Oracle; it does not process a real card or UPI payment."
    )

    connection = None

    try:
        connection = get_connection()

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    RS.RESERVATION_ID,
                    P.NAME,
                    R.SOURCE,
                    R.DESTINATION,
                    T.JOURNEY_DATE,
                    T.FARE,
                    RS.STATUS
                FROM RESERVATION RS
                JOIN PASSENGER P
                    ON P.PASSENGER_ID = RS.PASSENGER_ID
                JOIN TRIP T
                    ON T.TRIP_ID = RS.TRIP_ID
                JOIN ROUTE R
                    ON R.ROUTE_ID = T.ROUTE_ID
                WHERE UPPER(RS.STATUS) IN ('PENDING', 'CONFIRMED')
                  AND NOT EXISTS (
                      SELECT 1
                      FROM PAYMENT PY
                      WHERE PY.RESERVATION_ID = RS.RESERVATION_ID
                  )
                ORDER BY RS.RESERVATION_ID DESC
            """)
            payable_reservations = cursor.fetchall()

        st.subheader("Record a New Payment")

        if not payable_reservations:
            st.info(
                "There are no pending or confirmed reservations awaiting payment. "
                "Create a reservation first, or review the existing payment history below."
            )
        else:
            selected_payment_reservation = st.selectbox(
                "Select Reservation",
                payable_reservations,
                format_func=lambda row: (
                    f"Reservation {row[0]} — {row[1]} — "
                    f"{row[2]} to {row[3]} — ₹{row[5]:,.2f} — {row[6]}"
                ),
                key="payment_reservation_select"
            )

            st.write(f"**Passenger:** {selected_payment_reservation[1]}")
            st.write(
                f"**Journey:** {selected_payment_reservation[2]} → "
                f"{selected_payment_reservation[3]}"
            )
            st.write(f"**Journey Date:** {selected_payment_reservation[4]}")
            st.metric("Payment Amount", f"₹{selected_payment_reservation[5]:,.2f}")

            payment_method = st.selectbox(
                "Payment Method",
                ["UPI", "Cash", "Card", "Net Banking"],
                key="payment_method_select"
            )
            confirm_payment = st.checkbox(
                "I confirm that I want to record this payment.",
                key="confirm_payment_checkbox"
            )

            if st.button(
                "Record Payment",
                type="primary",
                disabled=not confirm_payment,
                key="record_payment_button"
            ):
                try:
                    reservation_id = selected_payment_reservation[0]
                    amount = selected_payment_reservation[5]

                    with connection.cursor() as cursor:
                        # Recheck inside the transaction to reduce duplicate-payment risk.
                        cursor.execute("""
                            SELECT COUNT(*)
                            FROM PAYMENT
                            WHERE RESERVATION_ID = :reservation_id
                        """, {"reservation_id": reservation_id})
                        existing_payment_count = cursor.fetchone()[0]

                        if existing_payment_count:
                            raise ValueError(
                                f"A payment already exists for reservation {reservation_id}."
                            )

                        cursor.execute("""
                            SELECT NVL(MAX(PAYMENT_ID), 0) + 1
                            FROM PAYMENT
                        """)
                        payment_id = cursor.fetchone()[0]

                        cursor.execute("""
                            INSERT INTO PAYMENT (
                                PAYMENT_ID,
                                RESERVATION_ID,
                                AMOUNT,
                                METHOD,
                                PAYMENT_STATUS
                            ) VALUES (
                                :payment_id,
                                :reservation_id,
                                :amount,
                                :method,
                                'PAID'
                            )
                        """, {
                            "payment_id": payment_id,
                            "reservation_id": reservation_id,
                            "amount": amount,
                            "method": payment_method
                        })

                        # Successful payment confirms a reservation that was pending.
                        cursor.execute("""
                            UPDATE RESERVATION
                            SET STATUS = 'CONFIRMED'
                            WHERE RESERVATION_ID = :reservation_id
                              AND UPPER(STATUS) = 'PENDING'
                        """, {"reservation_id": reservation_id})

                    connection.commit()
                    st.session_state.flash_message = (
                        f"Payment recorded successfully! Payment ID: {payment_id}. "
                        f"Reservation ID: {reservation_id}. Amount: ₹{amount:,.2f}. "
                        f"Method: {payment_method}. Status: PAID."
                    )
                    st.session_state.flash_type = "success"
                    st.rerun()

                except Exception as payment_error:
                    connection.rollback()
                    st.session_state.flash_message = (
                        f"Payment could not be recorded: {payment_error}"
                    )
                    st.session_state.flash_type = "error"
                    st.rerun()

        st.divider()
        st.subheader("Payment History")

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    PY.PAYMENT_ID,
                    PY.RESERVATION_ID,
                    P.NAME,
                    PY.AMOUNT,
                    PY.METHOD,
                    PY.PAYMENT_STATUS
                FROM PAYMENT PY
                LEFT JOIN RESERVATION RS
                    ON RS.RESERVATION_ID = PY.RESERVATION_ID
                LEFT JOIN PASSENGER P
                    ON P.PASSENGER_ID = RS.PASSENGER_ID
                ORDER BY PY.PAYMENT_ID DESC
            """)
            payment_rows = cursor.fetchall()

        payment_columns = [
            "Payment ID", "Reservation ID", "Passenger",
            "Amount (₹)", "Method", "Payment Status"
        ]
        payment_data = [dict(zip(payment_columns, row)) for row in payment_rows]
        st.dataframe(payment_data, use_container_width=True, hide_index=True)

    except Exception as error:
        st.error(f"Unable to load Payments module: {error}")

    finally:
        if connection:
            connection.close()


elif page == "Reports":
    st.header("📊 Reports and Analytics")
    st.caption("Generate reports directly from the Oracle database.")

    connection = None

    try:
        connection = get_connection()

        report_type = st.selectbox(
            "Select Report",
            [
                "Reservation Report",
                "Payment Report",
                "Trip Summary",
                "Cursor Reservation Summary"
            ],
            key="report_type"
        )

        if report_type == "Reservation Report":
            st.subheader("Reservation Report")

            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        RS.RESERVATION_ID,
                        P.NAME,
                        R.SOURCE,
                        R.DESTINATION,
                        T.JOURNEY_DATE,
                        S.SEAT_NO,
                        T.FARE,
                        RS.STATUS
                    FROM RESERVATION RS
                    JOIN PASSENGER P
                        ON P.PASSENGER_ID = RS.PASSENGER_ID
                    JOIN TRIP T
                        ON T.TRIP_ID = RS.TRIP_ID
                    JOIN ROUTE R
                        ON R.ROUTE_ID = T.ROUTE_ID
                    JOIN SEAT S
                        ON S.SEAT_ID = RS.SEAT_ID
                    ORDER BY RS.RESERVATION_ID DESC
                """)

                rows = cursor.fetchall()

            columns = [
                "Reservation ID",
                "Passenger",
                "Source",
                "Destination",
                "Journey Date",
                "Seat",
                "Fare (₹)",
                "Status"
            ]

            report_data = [
                dict(zip(columns, row))
                for row in rows
            ]

            st.metric("Total Reservations", len(rows))
            st.dataframe(
                report_data,
                use_container_width=True,
                hide_index=True
            )

        elif report_type == "Payment Report":
            st.subheader("Payment Report")

            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        PAYMENT_ID,
                        RESERVATION_ID,
                        AMOUNT,
                        METHOD,
                        PAYMENT_STATUS
                    FROM PAYMENT
                    ORDER BY PAYMENT_ID DESC
                """)

                rows = cursor.fetchall()

                cursor.execute("""
                    SELECT
                        COUNT(*),
                        NVL(SUM(
                            CASE
                                WHEN UPPER(PAYMENT_STATUS) = 'PAID'
                                THEN AMOUNT
                                ELSE 0
                            END
                        ), 0)
                    FROM PAYMENT
                """)

                payment_summary = cursor.fetchone()

            columns = [
                "Payment ID",
                "Reservation ID",
                "Amount (₹)",
                "Method",
                "Payment Status"
            ]

            report_data = [
                dict(zip(columns, row))
                for row in rows
            ]

            col1, col2 = st.columns(2)
            col1.metric("Payment Records", payment_summary[0])
            col2.metric(
                "Total Paid Amount",
                f"₹{payment_summary[1]:,.2f}"
            )

            st.dataframe(
                report_data,
                use_container_width=True,
                hide_index=True
            )

        elif report_type == "Cursor Reservation Summary":
            st.subheader("Cursor-Based Reservation Summary")
            st.caption(
                "This report uses an explicit PL/SQL cursor in Oracle to process "
                "reservation rows one by one."
            )
            cursor_summary = get_cursor_reservation_summary(connection)
            if cursor_summary.strip():
                st.code(cursor_summary, language="text")
            else:
                st.info("No reservations found.")

        elif report_type == "Trip Summary":
            st.subheader("Trip Summary")

            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        T.TRIP_ID,
                        R.SOURCE,
                        R.DESTINATION,
                        T.JOURNEY_DATE,
                        T.FARE,
                        COUNT(DISTINCT S.SEAT_ID) AS TOTAL_SEATS,
                        COUNT(DISTINCT
                            CASE
                                WHEN UPPER(RS.STATUS)
                                    IN ('PENDING', 'CONFIRMED')
                                THEN RS.RESERVATION_ID
                            END
                        ) AS ACTIVE_RESERVATIONS,
                        COUNT(DISTINCT
                            CASE
                                WHEN UPPER(RS.STATUS)
                                    = 'CONFIRMED'
                                THEN RS.RESERVATION_ID
                            END
                        ) * T.FARE AS CONFIRMED_FARE_TOTAL
                    FROM TRIP T
                    JOIN ROUTE R
                        ON R.ROUTE_ID = T.ROUTE_ID
                    LEFT JOIN SEAT S
                        ON S.VEHICLE_ID = T.VEHICLE_ID
                    LEFT JOIN RESERVATION RS
                        ON RS.TRIP_ID = T.TRIP_ID
                       AND RS.SEAT_ID = S.SEAT_ID
                    GROUP BY
                        T.TRIP_ID,
                        R.SOURCE,
                        R.DESTINATION,
                        T.JOURNEY_DATE,
                        T.FARE
                    ORDER BY T.TRIP_ID
                """)

                rows = cursor.fetchall()

            columns = [
                "Trip ID",
                "Source",
                "Destination",
                "Journey Date",
                "Fare (₹)",
                "Total Seats",
                "Active Reservations",
                "Confirmed Fare Total (₹)"
            ]

            report_data = [
                dict(zip(columns, row))
                for row in rows
            ]

            for row in report_data:
                row["Available Seats"] = max(
                    0,
                    row["Total Seats"] - row["Active Reservations"]
                )

            st.dataframe(
                report_data,
                use_container_width=True,
                hide_index=True
            )

            st.caption(
                "Active reservations include PENDING and CONFIRMED "
                "reservations. Confirmed fare totals are calculated "
                "from confirmed reservations, not payment records."
            )

    except Exception as error:
        st.error(f"Unable to generate report: {error}")

    finally:
        if connection:
            connection.close()
