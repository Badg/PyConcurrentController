import http.server
import socketserver
import handler

PORT = 8000

Handler = handler.UAVHandler

httpd = socketserver.TCPServer(("", PORT), Handler)

print("serving at port", PORT)
httpd.serve_forever()