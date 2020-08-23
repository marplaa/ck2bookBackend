import json
from channels.generic.websocket import WebsocketConsumer

import hashlib
import json
import logging
import re
import subprocess
from pathlib import Path
from shutil import move, rmtree, copy

import urllib3
import wget
from PIL import Image, ImageFilter, ImageEnhance
from bs4 import BeautifulSoup

production = True

logging.basicConfig(filename='log.log', level=logging.DEBUG, format='%(asctime)s %(levelname)-8s %(message)s')

logging.info('Starting consumer')

if production:
    luatex_prefix = '/usr/bin/'
    base_url = 'https://ck2book.coretechs.de:8000'
    media_dir = 'media/books'
else:
    luatex_prefix = ''
    base_url = 'http://localhost:8000'
    media_dir = 'media/books'


def crop_image(path, name, size, filter):
    logging.info("Cropping image " + name + ' to size ' + str(size[0]) + 'x' + str(size[1]))

    img = Image.open(str(path / (name + '.jpg')))
    ar_orig = img.size[0] / img.size[1]
    ar_crop = size[0] / size[1]

    # orig_width = crop_width
    if ar_orig < ar_crop:
        crop_height = int(img.size[0] / ar_crop)
        upper_left = int((img.size[1] - crop_height) / 2)
        box = (0, upper_left, img.size[0], crop_height + upper_left)
    else:
        crop_width = int(img.size[1] * ar_crop)
        upper_left = int((img.size[0] - crop_width) / 2)
        box = (upper_left, 0, crop_width + upper_left, img.size[1])

    cropped_img = img.crop(box)

    # resize

    image = cropped_img.resize((size[0], size[1]), Image.ANTIALIAS)

    # apply filters here
    filtered = ''
    for f in filter:

        if f == 'blur':
            image = image.filter(ImageFilter.GaussianBlur(float(filter[f])))
            filtered = '-f'
        elif f == 'brightness':
            image = ImageEnhance.Brightness(image).enhance(float(filter[f]))
            filtered = '-f'
        elif f == 'color':
            image = ImageEnhance.Color(image).enhance(float(filter[f]))
            filtered = '-f'
        elif f == 'contrast':
            image = ImageEnhance.Contrast(image).enhance(float(filter[f]))
            filtered = '-f'

    image.save(str(path / (name + '-' + str(size[0]) + 'x' + str(size[1]) + filtered + '.jpg')))


def makelist(table):
    result = []
    empty = True

    rows = table.findAll('tr')
    for row in rows:
        new_row = []
        allcols = row.findAll('td')
        for col in allcols:
            empty = True
            thestrings = []

            for thestring in col.stripped_strings:
                thestring = re.sub(r'\s+', ' ', thestring)

                thestrings.append(thestring)
                if not thestring.split() == '':
                    empty = False
            thetext = ''.join(thestrings)
            new_row.append(thetext)
        # check if row would be empty
        if not empty:
            result.append(new_row)
    return result


def soupify(url):
    if "/drucken/" not in url:
        url = url.replace("/rezepte/", "/rezepte/drucken/")

    http = urllib3.PoolManager()
    response = http.request('GET', url)

    return BeautifulSoup(response.data, 'html.parser')


class BookConsumer(WebsocketConsumer):

    def connect(self):
        self.accept()

    def disconnect(self, close_code):
        pass

    def receive(self, text_data):
        logging.info('message received...')
        text_data_json = json.loads(text_data)
        data = text_data_json

        self.send(text_data=json.dumps({
            'type': 'message',
            'data': data['id']
        }))

        self.create_tex_file(data)

    def create_tex_file(self, data):
        logging.info("creating tex file")
        # data = json.loads(request.body)
        file_id = data['id']  # hashlib.md5(bytearray(data['content'], encoding="utf-8")).hexdigest()
        directory_path = Path('temp') / Path(file_id)

        try:
            directory_path.mkdir()
            (directory_path / 'images').mkdir()
        except:
            logging.error("Error while mkdir " + str(directory_path))

        try:
            f = open(directory_path / (file_id + '.tex'), "w", encoding='utf-8')
            f.write(data['content'])
            f.close()
        except:
            logging.error("Error while writing tex tile")

        self.download_images(data['images'], directory_path / 'images')
        logging.info("images downloaded")

        # make_zip(str(directory_path), file_id)

        ok = self.compile_latex(directory_path, file_id)

        if ok:
            logging.info('moving pdf file to /media...')
            try:
                (Path(media_dir) / file_id).mkdir()
                move(directory_path / (file_id + '.pdf'), Path(media_dir) / file_id / 'Kochbuch.pdf')

            except:
                logging.error('error while moving pdf file to /media')

            try:
                if production:
                    logging.info('removing directory...')
                    rmtree(str(directory_path))
            except:
                logging.error('error while removing directory')

        else:
            logging.error('error while compiling texfile')

        if ok:
            self.send(text_data=json.dumps(
                {'type': 'book', 'data': {'ok': ok, 'url': base_url + '/media/books/' + file_id + '/Kochbuch.pdf'}}))
        else:
            self.send(text_data=json.dumps({'type': 'book', 'data': {'ok': ok}}))

    def compile_latex(self, directory, file_id):
        logging.info('compiling latex...')
        ok = False
        self.send_message('message', 51, 'Kompiliere (Runde 1 von 2)')
        if not subprocess.run([luatex_prefix + "lualatex", file_id + '.tex'], cwd=str(directory)).returncode:
            self.send_message('message', 75, 'Kompiliere (Runde 2 von 2)')
            ok = not subprocess.run([luatex_prefix + "lualatex", file_id + '.tex'],
                                    cwd=str(directory)).returncode

        return ok

    def send_message(self, type, progress, data):
        self.send(text_data=json.dumps({
            'type': type,
            'progress': progress,
            'data': data
        }))

    def download_images(self, images, path):
        logging.info("downloading images to:" + str(path))
        i = 1

        for image in images:

            allowed_image_hosts = [
                'https://img.chefkoch-cdn.de/rezepte',
                'https://marplaa.github.io/ck2book/'
            ]

            checked = False
            for host in allowed_image_hosts:
                checked |= image['url'].startswith(host)

            img_hash = hashlib.md5(bytearray(image['url'], encoding="ascii")).hexdigest()
            orig_name = img_hash + '.jpg'

            if checked:

                self.send_message('message', int(i / (len(images)) * 0.5 * 100), 'Lade Bild: ' + image['url'])


                logging.info('downloading (' + str(i) + ' of ' + str(len(images)) + '): ' + str(image['url']))
                try:
                    wget.download(image['url'], out=str(path / orig_name))
                except Exception as ex:
                    logging.error("could not download image: " + image['url'])
                    copy(str(Path('static') / 'imagenotfound.jpg'), str(path / orig_name))

            else:
                self.send_message('message', int(i / (len(images)) * 0.5 * 100), 'Fehler: Kein erlaubtes Bild: ' + image['url'])
                copy(str(Path('static') / 'imagenotfound.jpg'), str(path / orig_name))
                i = i + 1

            # iterate through all resolutions per picture
            for size in image['sizes']:
                resolution = int(size['size'].split('x')[0]), int(size['size'].split('x')[1])
                crop_image(path, img_hash, resolution, size['filter'])
            i = i + 1
