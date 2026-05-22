import bcrypt

password = "Admin@2026!".encode()
hashed = bcrypt.hashpw(password, bcrypt.gensalt())

print(hashed.decode())
