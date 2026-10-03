"""Password gate and optional authenticated, streaming encryption for backups."""
import hashlib
import hmac
import os
from pathlib import Path

def password_hash(password,salt=None):
    if len(password)<10:raise ValueError('Минимум 10 символов')
    salt=salt or os.urandom(16)
    derived=hashlib.scrypt(password.encode(),salt=salt,n=32768,r=8,p=1,maxmem=128*1024*1024,dklen=32)
    return salt.hex()+':'+derived.hex()

def verify(password,stored):
    try:
        salt,expected=stored.split(':');actual=password_hash(password,bytes.fromhex(salt)).split(':')[1]
        return hmac.compare_digest(actual,expected)
    except (ValueError,TypeError):return False

def encrypt_backup(source,destination,password):
    from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
    if len(password)<10:raise ValueError('Минимум 10 символов')
    salt=os.urandom(16);nonce=os.urandom(12)
    key=hashlib.scrypt(password.encode(),salt=salt,n=32768,r=8,p=1,maxmem=128*1024*1024,dklen=32)
    header=b'SGBAK1'+salt+nonce
    encryptor=Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor();encryptor.authenticate_additional_data(header)
    with open(source,'rb') as src,open(destination,'wb') as dst:
        dst.write(header)
        for chunk in iter(lambda:src.read(1024*1024),b''):dst.write(encryptor.update(chunk))
        dst.write(encryptor.finalize());dst.write(encryptor.tag)

def decrypt_backup(source,destination,password):
    from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
    try:
        with open(source,'rb') as src:
            header=src.read(34)
            if len(header)!=34 or not header.startswith(b'SGBAK1'):raise ValueError('Неизвестный формат')
            src.seek(-16,2);tag=src.read(16);end=src.tell()-16;src.seek(34)
            key=hashlib.scrypt(password.encode(),salt=header[6:22],n=32768,r=8,p=1,maxmem=128*1024*1024,dklen=32)
            decryptor=Cipher(algorithms.AES(key),modes.GCM(header[22:],tag)).decryptor();decryptor.authenticate_additional_data(header)
            with open(destination,'wb') as dst:
                while src.tell()<end:dst.write(decryptor.update(src.read(min(1024*1024,end-src.tell()))))
                dst.write(decryptor.finalize())
    except Exception:
        Path(destination).unlink(missing_ok=True)
        raise ValueError('Неверный пароль или повреждённая копия') from None

def login(db,parent=None):
    from PyQt6.QtWidgets import QInputDialog,QLineEdit,QMessageBox
    import time
    stored=db.get_setting('password_hash','')
    if not stored:return True
    until=float(db.get_setting('login_until','0'))
    if time.time()<until:
        QMessageBox.warning(parent,'Вход','Повторите вход через минуту.');return False
    for _ in range(5):
        password,ok=QInputDialog.getText(parent,'Вход','Пароль:',QLineEdit.EchoMode.Password)
        if not ok:return False
        if verify(password,stored):db.set_setting('login_failures','0');return True
        attempts=int(db.get_setting('login_failures','0'))+1;db.set_setting('login_failures',attempts)
        if attempts>=5:
            db.set_setting('login_until',time.time()+60);db.set_setting('login_failures','0');return False
    return False
