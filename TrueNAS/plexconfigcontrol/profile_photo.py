"""Bounded profile image storage confined to the application ixVolume."""
import fcntl
import hashlib
import io
import os
import stat
from contextlib import contextmanager
from pathlib import Path

MAX_UPLOAD=5*1024*1024
MAX_PIXELS=20_000_000
MAX_STORED=2*1024*1024


class InvalidPhoto(ValueError): pass
class PhotoChanged(ValueError): pass


class ProfilePhoto:
    def __init__(self,state_directory):
        self.directory=Path(state_directory)
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=self.directory/'profile-photo.png'
        self.pending=self.directory/'profile-photo.pending'
        with self._lock(): self._cleanup_pending()

    @contextmanager
    def _lock(self):
        fd=os.open(self.directory/'profile-photo.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode): raise OSError('Invalid photo lock')
            fcntl.flock(fd,fcntl.LOCK_EX)
            yield
        finally: os.close(fd)

    def _sync(self):
        fd=os.open(self.directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try: os.fsync(fd)
        finally: os.close(fd)

    def _cleanup_pending(self):
        try: info=self.pending.lstat()
        except FileNotFoundError: return
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1:
            raise OSError('Invalid pending profile file')
        self.pending.unlink(); self._sync()

    @staticmethod
    def normalize(data):
        from PIL import Image, ImageOps, UnidentifiedImageError
        if not isinstance(data,bytes) or not 0<len(data)<=MAX_UPLOAD:
            raise InvalidPhoto('Choose a JPEG or PNG photo up to 5 MiB')
        try:
            with Image.open(io.BytesIO(data),formats=('JPEG','PNG')) as image:
                if image.width*image.height>MAX_PIXELS:
                    raise InvalidPhoto('Photo exceeds the 20 megapixel limit')
                if getattr(image,'is_animated',False):
                    raise InvalidPhoto('Animated profile photos are not supported')
                image.verify()
            with Image.open(io.BytesIO(data),formats=('JPEG','PNG')) as image:
                image.load()
                oriented=ImageOps.exif_transpose(image)
                fitted=ImageOps.fit(oriented.convert('RGBA'),(512,512),method=Image.Resampling.LANCZOS)
                # A new pixel-only image strips EXIF, GPS, comments and profiles.
                clean=Image.new('RGBA',(512,512));clean.paste(fitted)
                output=io.BytesIO();clean.save(output,format='PNG')
                result=output.getvalue()
                if len(result)>MAX_STORED: raise InvalidPhoto('Normalized photo is too large')
                return result
        except InvalidPhoto: raise
        except (OSError,ValueError,SyntaxError,UnidentifiedImageError,Image.DecompressionBombError):
            raise InvalidPhoto('Photo is corrupt or is not a supported JPEG/PNG image') from None

    def upload(self,data):
        with self._lock():
            self._cleanup_pending()
            normalized=self.normalize(data)
            try:
                fd=os.open(self.pending,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb') as output:
                    output.write(normalized);output.flush();os.fsync(output.fileno())
                # Replace only this application's fixed image, never caller paths.
                if self.path.is_symlink(): raise OSError('Invalid profile image storage')
                os.replace(self.pending,self.path);self._sync()
            finally:
                self._cleanup_pending()
            return {'present':True,'revision':hashlib.sha256(normalized).hexdigest()}

    def read(self):
        with self._lock():
            try: fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            except FileNotFoundError: return None
            with os.fdopen(fd,'rb') as source:
                info=os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size>MAX_STORED: raise OSError('Invalid profile image storage')
                data=source.read(MAX_STORED+1)
                if len(data)>MAX_STORED: raise OSError('Invalid profile image storage')
                return data

    def status(self):
        data=self.read()
        return {'present':data is not None,'revision':hashlib.sha256(data).hexdigest() if data is not None else None}

    def remove(self,confirmed=False,expected_revision=None):
        if confirmed is not True: raise ValueError('Confirm profile photo removal')
        with self._lock():
            try: info=self.path.lstat()
            except FileNotFoundError: return {'present':False,'revision':None}
            if not stat.S_ISREG(info.st_mode): raise OSError('Invalid profile image storage')
            if expected_revision is not None:
                fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
                with os.fdopen(fd,'rb') as source:
                    if os.fstat(source.fileno()).st_size>MAX_STORED: raise OSError('Invalid profile image storage')
                    current=hashlib.sha256(source.read(MAX_STORED+1)).hexdigest()
                if current!=expected_revision: raise PhotoChanged('Profile photo changed. Reload before removing it.')
            self.path.unlink();self._sync()
            return {'present':False,'revision':None}
