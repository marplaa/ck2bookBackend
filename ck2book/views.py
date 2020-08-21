import logging
import re
import urllib3
from bs4 import BeautifulSoup
from django.http import HttpResponse, JsonResponse

logging.basicConfig(filename='log.log', level=logging.DEBUG, format='%(asctime)s %(levelname)-8s %(message)s')

logging.info('Starting...')


def scrape_recipe(request):
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

    try:
        recipe['images'] = get_images(url)
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
def get_images(url):
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
