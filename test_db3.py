import pymysql
try:
    conn = pymysql.connect(host='127.0.0.1', port=3307, user='supplyforge', password='change-me', database='supplyforge')
    print("Connected successfully on 3307!")
    conn.close()
except Exception as e:
    print("Error:", e)
