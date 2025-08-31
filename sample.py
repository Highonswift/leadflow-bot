import psycopg2
from urllib.parse import urlparse

conn = None
def initialize_db(DATABASE_URL):
    global conn

    # Parse the URL
    result = urlparse(DATABASE_URL)
    username = result.username
    password = result.password
    database = result.path[1:]  # remove leading '/'
    hostname = result.hostname
    port = result.port

    # Connect
    conn = psycopg2.connect(
        dbname=database,
        user=username,
        password=password,
        host=hostname,
        port=port,
        sslmode="require"
    )

def getAgentDetails(id):
    cur = conn.cursor()

    # Example query
    cur.execute('SELECT * FROM "User" LIMIT 5;')  # Prisma uses quoted table names
    rows = cur.fetchall()
    for row in rows:
        print(row)

    cur.close()
    conn.close()
