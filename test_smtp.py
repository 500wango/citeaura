import smtplib, ssl
try:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
except Exception as e:
    print(e)
