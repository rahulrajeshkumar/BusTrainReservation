import oracledb

ORACLE_CLIENT_PATH = r"C:\oracle\instantclient_19_26\instantclient_19_32"

oracledb.init_oracle_client(lib_dir=ORACLE_CLIENT_PATH)


def get_connection():
    connection = oracledb.connect(
        user="SYSTEM",
        password="rahul2006",
        dsn="localhost:1521/XE"
    )
    return connection


def test_connection():
    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT USER FROM DUAL")
            result = cursor.fetchone()

            print("Oracle connection successful!")
            print("Connected user:", result[0])
    finally:
        connection.close()


if __name__ == "__main__":
    test_connection()
