from psycopg2 import pool
import psycopg2.extras
import json
from urllib.parse import urlparse

connection_pool = None
def initialize_db(DATABASE_URL):
    global connection_pool

    result = urlparse(DATABASE_URL)
    username = result.username
    password = result.password
    database = result.path[1:]
    hostname = result.hostname
    port = result.port

    # Create connection pool
    connection_pool = pool.SimpleConnectionPool(
        minconn=1,
        maxconn=5,
        dbname=database,
        user=username,
        password=password,
        host=hostname,
        port=port,
        sslmode="require"
    )

SYSTEM_INSTRUCTION = """
You are a friendly, professional, and efficient virtual hotel booking assistant for HighOnSwift Hotel. 
Your purpose is to help customers book hotel rooms, answer their questions, and provide a seamless, stress-free experience. 
Be concise. Sound helpful, polite, and confident. Ask follow-up questions to gather necessary information. 
A voice agent's output is spoken, and these symbols can be read aloud as "asterisk" or "underscore," which would sound unnatural and confuse the user. 
DON'T make assumptions or fill in missing information without confirmation. 
DON'T provide information that is not requested unless it is critical for the booking process (e.g., reminding them of cancellation policies).
DON'T interrupt the user. 
DON'T use formatting in your responses, like bold, italics, or other special characters. 
"""

def getAgentDetails(id):
    data = {
        'name': 'Alex',
        'subtext': 'Booking Assistant',
        'welcome_message': "Welcome to The HighOnSwift Hotel's booking service. How can I help you today?",
        'prompt': SYSTEM_INSTRUCTION
    }
    conn = connection_pool.getconn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute('SELECT * FROM "Assistant" WHERE id = %s LIMIT 1;', (id,))
        row = cur.fetchone()

        # if row:
            # data = {
            #     'name': row['name'],
            #     'prompt': '',
            # }

        cur.close()
    except Exception as e:
        print(e)
    finally:
        connection_pool.putconn(conn)

    return data

def getConversationId(session_id):
    conversation_id = None
    conn = connection_pool.getconn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute('SELECT * FROM "Conversation" WHERE "sessionId" = %s LIMIT 1;', (session_id,))
        row = cur.fetchone()

        if row:
            conversation_id = row['id']
    except Exception as e:
        print(e)
    finally:
        connection_pool.putconn(conn)
    return conversation_id

def getUserId(agent_id):
    user_id = None
    conn = connection_pool.getconn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute('SELECT * FROM "Assistant" WHERE id = %s LIMIT 1;', (agent_id,))
        row = cur.fetchone()

        if row:
            user_id = row['userId']
    except Exception as e:
        print(e)
    finally:
        connection_pool.putconn(conn)
    return user_id

def getMessages(session_id):
    messages = []
    conversation_id = getConversationId(session_id)
    
    if conversation_id:
        conn = connection_pool.getconn()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute('SELECT * FROM "Message" WHERE "conversationId" = %s;', (conversation_id,))
            rows = cur.fetchall()

            for message_row in rows:
                messages.append({
                    'role': message_row['sender'],
                    'parts': [message_row['content']]
                })

            cur.close()
        except Exception as e:
            print(e)
        finally:
            connection_pool.putconn(conn)
    
    return messages

def createConversation(agent_id, session_id):
    userId = getUserId(agent_id)

    if userId:
        conn = connection_pool.getconn()
        try:
            query = '''
            INSERT INTO "Conversation" ("userId", "sessionId", "customerName", "source", "startedAt", "updatedAt")
            VALUES (%s, %s, %s, %s, NOW(), NOW())
            RETURNING *;
            '''
                    
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(query, (userId, session_id, '', ''))
            row = cur.fetchone()
            
            conn.commit()
            cur.close()
        except Exception as e:
            print(e)
        finally:
            connection_pool.putconn(conn)

def addMessage(session_id, sender, content):
    conversation_id = getConversationId(session_id)
    
    if conversation_id:
        conn = connection_pool.getconn()
        try:
            query = '''
            INSERT INTO "Message" ("conversationId", "sender", "content", "messageType", "timestamp")
            VALUES (%s, %s, %s, %s, NOW())
            RETURNING *;
            '''
                    
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(query, (conversation_id, sender, content, 'text'))
            row = cur.fetchone()
            
            conn.commit()
            cur.close()
        except Exception as e:
            print(e)
        finally:
            connection_pool.putconn(conn)


if __name__ == '__main__':
    DATABASE_URL = "postgres://f4508c4af694309d506c5e7d279b4d42bab5d7e798bbe8276286782db68cb6bc:sk_aTufVVM93xmW09Nj2AUlZ@db.prisma.io:5432/postgres?sslmode=require"
    initialize_db(DATABASE_URL)
    print(getMessages('a8etuzhjoCFFqIbpAAAB'))