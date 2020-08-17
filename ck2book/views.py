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
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

logging.basicConfig(filename='log.log', level=logging.DEBUG, format='%(asctime)s %(levelname)-8s %(message)s')

logging.info('Starting...')

production = False

if production:
    production_prefix = '/usr/bin/'
    base_url = ''
else:
    production_prefix = ''
    base_url = 'http://localhost:8000'


def index(request):
    return HttpResponse("Hello, world. You're at the polls index.")


def get_recipe_data_json_get(request):
    url = request.GET.get('url')
    print(url)
    recipe_data = get_recipe_data(url)

    return JsonResponse(recipe_data)


def get_recipe_data(url):
    recipe = {"url": url}
    soup = soupify(url)
    content = soup.find("div", {"class": "print__content_left"}).find("p")
    # print(soup.find("div", {"class": "ds-box"}).get_text())

    recipe['title'] = soup.find("a", {"class": "bi-recipe-title"}).getText()
    try:
        recipe['subtitle'] = soup.find("div", {"id": "content"}).find("strong").getText()
    except Exception:
        pass

    recipe['ingredients'] = makelist(soup.find("table", {"class": "print__ingredients"}))

    recipe['recipeInfo'] = makelist(soup.find("table", {'id': 'recipe-info'}).extract())

    recipe['text'] = re.sub(r'\s+', ' ', content.get_text('</br>', strip=True)).replace('\n', '')

    # get images

    # soup = soupify(url.replace("/drucken",""))
    # print(soup.find("div", {"class": "recipe-image"}))
    # print(url.replace("/drucken",""))
    # imgs = soup.find("div", {"class": "recipe-image"}).find_all("amp-img")
    image = soup.find("figure").find("img")
    # for image in imgs:

    try:
        recipe['images'] = getImages(url)
    except:
        pass

    recipe['image'] = recipe['images'][0]

    return recipe


def soupify(url):
    if "/drucken/" not in url:
        url = url.replace("/rezepte/", "/rezepte/drucken/")

    http = urllib3.PoolManager()
    response = http.request('GET', url)

    return BeautifulSoup(response.data, 'html.parser')


# todo check if images überhaupt vorhanden sind unter bilderübersicht
def getImages(url):
    logging.info('retrieving images...')
    url = url.replace("/rezepte/", "/rezepte/bilderuebersicht/")
    http = urllib3.PoolManager()

    img_list = []
    try:
        logging.info("getting images from url: " + url)
        response = http.request('GET', url)

        soup = BeautifulSoup(response.data, 'html.parser')
        # print(soup.find("div", {'class': 'recipe-images'}))
        images = soup.find("div", {'class': 'recipe-images'}).findAll('amp-img')
        for img in images:
            image = re.sub(r'/crop-[0-9x]*/', '/crop-960x640/', img.get('src'))
            img_list.append(image)

    except Exception as ex:
        print(ex.args)
        logging.error('error while getting images')

    return img_list


@csrf_exempt
def create_tex_file(request):
    logging.info("creating tex file")
    data = json.loads(request.body)
    file_id = hashlib.md5(bytearray(data['content'], encoding="utf-8")).hexdigest()
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

    download_images(data['images'], directory_path / 'images')
    logging.info("images downloaded")

    # make_zip(str(directory_path), file_id)

    ok = compile_latex(directory_path, file_id)

    if True:  # ok:
        logging.info('moving pdf file to static...')
        try:
            (Path('media/books') / file_id).mkdir()
            move(directory_path / (file_id + '.pdf'), Path('media/books') / file_id / 'Kochbuch.pdf')
            if production:
                rmtree(str(directory_path))
        except:
            pass
    else:
        logging.error('error while compiling texfile')

    # print(data)
    return JsonResponse({'ok': ok, 'url': base_url + '/media/books/' + file_id + '/Kochbuch.pdf'})


def compile_latex(directory, file_id):
    logging.info('compiling latex...')
    ok = False
    if not subprocess.run([production_prefix + "lualatex", file_id + '.tex'], cwd=str(directory)).returncode:
        ok = not subprocess.run([production_prefix + "lualatex", file_id + '.tex'],
                                cwd=str(directory)).returncode

    return ok


def download_images(images, path):
    logging.info("downloading images to:" + str(path))
    i = 1
    for image in images:
        hash = hashlib.md5(bytearray(image['url'], encoding="ascii")).hexdigest()
        orig_name = hash + '.jpg'
        logging.info('downloading (' + str(i) + ' of ' + str(len(images)) + '): ' + str(image['url']))
        try:
            wget.download(image['url'], out=str(path / orig_name))
        except Exception as ex:
            logging.error("could not download image: " + image['url'])
            copy(str(Path('static') / 'imagenotfound.jpg'), str(path / orig_name))

        # iterate through all resolutions per picture
        for size in image['sizes']:
            # name = hash + '-' + res + '.jpg'

            resolution = int(size['size'].split('x')[0]), int(size['size'].split('x')[1])
            crop_image(path, hash, resolution, size['filter'])
        i = i + 1


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
