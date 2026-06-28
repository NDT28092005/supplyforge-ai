import pymysql
try:
    conn = pymysql.connect(host='127.0.0.1', port=3306, user='supplyforge', password='change-me', database='supplyforge')
    print("Connected successfully!")
    conn.close()
except Exception as e:
    print("Error:", e)
