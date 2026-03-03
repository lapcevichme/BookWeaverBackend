import argparse
import io
import json
import logging
import random
import re
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import requests
import urllib3

try:
    from ebooklib import epub
    from bs4 import BeautifulSoup

    EBOOKLIB_AVAILABLE = True
except ImportError:
    EBOOKLIB_AVAILABLE = False
    print("⚠️ ebooklib и/или beautifulsoup4 не установлены - epub-вывод будет недоступен")
    print("   pip install ebooklib beautifulsoup4 lxml")

try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    # реально 1 том был 100 мб вместо 10
    print("⚠️ Pillow не установлен - картинки будут встраиваться БЕЗ сжатия (возможен огромный размер EPUB)")
    print("   pip install Pillow")

import config

logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class RanobeLibLoader:
    """
    Класс для загрузки ранобэ с ranobelib.me в формат txt или epub.
    """

    def __init__(self, debug_requests: bool = False):
        self.api_url = config.RANOBELIB_API_BASE_URL
        self.img_url = config.RANOBELIB_IMAGE_BASE_URL
        self.headers = config.RANOBELIB_HEADERS.copy()

        if config.RANOBELIB_USER_TOKEN:
            self.headers['Authorization'] = f"Bearer {config.RANOBELIB_USER_TOKEN}"
        else:
            logger.warning("⚠️ RANOBELIB_USER_TOKEN не найден. Доступ к API может быть ограничен.")

        self.debug_requests = debug_requests
        self.epub_book = None
        self.chapter_items = []
        self.embedded_images = {}
        self.output_format = "txt"

        self.max_image_width = 1200
        self.image_quality = 75

        logger.info("RanobeLibLoader инициализирован.")

    def _debug_log_request(self, method: str, url: str, response: Optional[requests.Response] = None, **kwargs):
        if not self.debug_requests:
            return

        print(f"\n[DEBUG REQUEST] {method} {url}")
        print("Headers:", json.dumps(dict(self.headers), indent=2, ensure_ascii=False))

        if 'data' in kwargs or 'json' in kwargs:
            body = kwargs.get('data') or kwargs.get('json')
            if isinstance(body, dict):
                print("Body:", json.dumps(body, indent=2, ensure_ascii=False))
            else:
                print("Body:", body)

        if response:
            print(f"[DEBUG RESPONSE] Status: {response.status_code}")
            print("Response Headers:", dict(response.headers))
            try:
                content = response.json()
                print("Response JSON:", json.dumps(content, indent=2, ensure_ascii=False))
            except Exception:
                print("Response Text (first 1000 chars):", response.text[:1000])

    def run(self, url: str, output_dir: Optional[Path] = None, download_images: bool = False,
            max_volume: Optional[int] = None, output_format: str = "txt"):

        self.output_format = output_format.lower()
        if self.output_format == "epub" and not EBOOKLIB_AVAILABLE:
            logger.error("Невозможно создать EPUB: ebooklib не установлен")
            return

        full_id, numeric_id = self._extract_ids(url)
        if not full_id:
            logger.error(f"Некорректный URL: {url}")
            return

        manga_info = self._fetch_ranobe_data(full_id)
        if not manga_info:
            return

        branches = self._fetch_branches(numeric_id)
        branch_id = self._select_best_branch(branches)

        # TODO - вернуть возможность ветку выбирать, наверное нужно это. Но через консоль неприятно конечно
        if not branch_id:
            logger.error("Не удалось определить ветку перевода.")
            return

        ranobe_title = self._format_label(manga_info)
        slug = manga_info.get('slug', full_id)
        folder_name = f"{slug} [{numeric_id}]"
        folder_name = re.sub(r'[<>:"/\\|?*]', '_', folder_name)

        base_path = output_dir if output_dir else config.INPUT_DIR
        save_dir = base_path / folder_name
        save_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"📁 Директория сохранения: {save_dir}")

        cover_filename = self._download_cover(manga_info, save_dir)
        self._save_metadata(save_dir, manga_info, url, cover_filename)

        chapters = self._fetch_chapters(full_id)
        if not chapters:
            logger.warning("Главы не найдены.")
            return

        if max_volume:
            chapters = [c for c in chapters if int(c.get('volume', 0)) <= max_volume]
            logger.info(f"Фильтр включен: загрузка до {max_volume} тома.")

        total = len(chapters)
        logger.info(f"Найдено глав для загрузки: {total}")

        if self.output_format == "epub":
            self._init_epub_book(manga_info, url, cover_filename, save_dir)

        for i, ch in enumerate(chapters):
            vol = ch.get('volume', '1')
            num = ch.get('number', '0')
            ch_name = ch.get('name', '').strip()

            ch_display = f"Том {vol} Глава {num}"
            if ch_name:
                ch_display += f" - {ch_name}"

            # TODO - норм прогресс бар сделать
            if i == 0 or (i + 1) % 5 == 0 or i == total - 1:
                logger.info(f"--> Обработка: {ch_display} ({i + 1}/{total})")

            try:
                data = self._fetch_chapter_content(full_id, vol, num, branch_id)
                if not data:
                    logger.warning(f"Пустой контент: Том {vol} Глава {num}")
                    continue

                text = self._parse_content_node(data.get('content'), data.get('attachments', []), download_images)

                safe_ch_name = re.sub(r'[<>:"/\\|?*]', '_', ch_name[:80]) if ch_name else f"ch_{num.replace('.', '_')}"

                chapter_url = f"https://ranobelib.me/ru/{manga_info.get('slug_url') or full_id}/read/v{vol}/c{num}?bid={branch_id}"

                if self.output_format == "epub":
                    self._add_chapter_to_epub(text, vol, num, ranobe_title, ch_display, chapter_url)
                else:
                    vol_path = save_dir / f"vol_{str(vol).zfill(2)}"
                    vol_path.mkdir(exist_ok=True)
                    file_path = vol_path / f"{num.replace('.', '_')} — {safe_ch_name}.txt"
                    content_to_write = f"{ranobe_title}\n{ch_display}\n\n{text}"
                    file_path.write_text(content_to_write, encoding='utf-8')

                # По идее 429 только с VPN и прокси вылезала. Не уверен что нужен такой большой сон, протестить без впн побольше
                time.sleep(1.8 + random.uniform(0, 0.9))

            except Exception as e:
                logger.error(f"Ошибка при скачивании {vol}-{num}: {e}")

        if self.output_format == "epub":
            self._finalize_epub(save_dir, ranobe_title)

        logger.info("🎉 Загрузка ранобэ завершена!")

    def _make_request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        max_retries = 5
        for attempt in range(max_retries):
            try:
                response = requests.request(
                    method, url, headers=self.headers, verify=False, timeout=15, **kwargs
                )

                self._debug_log_request(method, url, response, **kwargs)

                if response.status_code == 429:
                    wait = (2 ** attempt) + random.uniform(0, 2)
                    logger.warning(f"429 Too Many Requests - ждём {wait:.1f} сек (попытка {attempt + 1}/{max_retries})")
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                return response

            except requests.exceptions.HTTPError as e:
                self._debug_log_request(method, url, e.response, **kwargs)
                if e.response and e.response.status_code == 429:
                    continue
                logger.error(f"HTTP ошибка {url}: {e}")
                return None
            except Exception as e:
                logger.error(f"Ошибка запроса {url}: {e}")
                return None

        logger.error(f"Превышено количество попыток для {url}")
        return None

    def _extract_ids(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        match = re.search(r'ranobelib\.me/(?:ru/book/)?((\d+)--[\w\-]+)', url)
        if match:
            return match.group(1), match.group(2)

        match_simple = re.search(r'ranobelib\.me/(?:ru/book/)?([\w\-]+)', url)
        if match_simple:
            full_id = match_simple.group(1)
            numeric_id_match = re.match(r'^\d+', full_id)
            numeric_id = numeric_id_match.group(0) if numeric_id_match else None
            return full_id, numeric_id
        return None, None

    def _fetch_ranobe_data(self, full_id: str) -> Optional[Dict]:
        url = f"{self.api_url}/manga/{full_id}"

        # Обход 422 с полями - TODO - вынести куда-то поля
        wanted_fields = [
            "background", "eng_name", "otherNames", "summary", "releaseDate",
            "type_id", "caution", "views", "close_view", "rate_avg", "rate",
            "genres", "tags", "teams", "user", "franchise", "authors", "publisher",
            "userRating", "moderated", "metadata", "metadata.count",
            "metadata.close_comments", "manga_status_id", "chap_count",
            "status_id", "artists", "format"
        ]

        params = [("fields[]", field) for field in wanted_fields]

        resp = self._make_request("GET", url, params=params)
        if resp:
            data = resp.json().get('data')
            if data:
                return data

        # Fallback, но вроде бы все подобрал. Главное чтобы апи не сменили снова xd
        logger.warning("Запрос с fields[] провалился - пробуем минимальный")
        resp = self._make_request("GET", url)
        return resp.json().get('data') if resp else None

    def _fetch_branches(self, numeric_id: str) -> List[Dict]:
        url = f"{self.api_url}/branches/{numeric_id}?team_defaults=1"
        resp = self._make_request("GET", url)
        return resp.json().get('data', []) if resp else []

    def _select_best_branch(self, branches: List[Dict]) -> Optional[int]:
        if not branches:
            return None
        selected = branches[0]
        team_name = selected['teams'][0].get('name') if selected.get('teams') else "Unknown"
        logger.info(f"Выбрана команда: {team_name} (ID: {selected.get('id')})")
        return selected.get('id')

    def _fetch_chapters(self, full_id: str) -> List[Dict]:
        url = f"{self.api_url}/manga/{full_id}/chapters"
        resp = self._make_request("GET", url)
        if not resp:
            return []

        chapters = resp.json().get('data', [])
        chapters.sort(key=lambda x: x.get('index', 0))

        for ch in chapters:
            ch_name = ch.get('name', '').strip()
            if not ch_name and ch.get('number'):
                ch_name = f"Глава {ch.get('number')}"
            ch['display_name'] = ch_name

        return chapters

    def _fetch_chapter_content(self, full_id: str, volume: str, number: str, branch_id: int) -> Optional[Dict]:
        url = f"{self.api_url}/manga/{full_id}/chapter"
        params = {'volume': volume, 'number': number, 'branch_id': branch_id}
        resp = self._make_request("GET", url, params=params)
        return resp.json().get('data', {}) if resp else None

    def _parse_content_node(self, content_node: Any, attachments: List[Dict], include_images: bool) -> str:
        if not isinstance(content_node, dict): return ""

        image_map = {}
        for att in attachments:
            img_url = att.get('url', '')
            if img_url.startswith('/uploads/'):
                img_url = f"https://ranobelib.me{img_url}"
            elif not img_url.startswith('http'):
                img_url = f"{self.img_url}{img_url}"
            image_map[att['name']] = img_url

        text_parts = []

        def _extract(node):
            if isinstance(node, list):
                for item in node: _extract(item)
                return
            if not isinstance(node, dict): return

            t = node.get('type')

            if include_images and t == 'image':
                try:
                    imgs = node.get('attrs', {}).get('images', [])
                    if imgs and (img_id := imgs[0].get('image')) in image_map:
                        text_parts.append(f"\n[Image: {image_map[img_id]}]\n")
                except Exception:
                    pass

            if t == 'text' and 'text' in node:
                text_parts.append(node['text'])

            if t == 'hardBreak':
                text_parts.append('\n')

            if 'content' in node and isinstance(node['content'], list):
                for child in node['content']: _extract(child)
                if t in ('paragraph', 'div'):
                    text_parts.append('\n\n')

        _extract(content_node)
        return re.sub(r'\n{3,}', '\n\n', "".join(text_parts)).strip()

    def _optimize_image_data(self, image_data: bytes) -> Tuple[bytes, str]:
        """Ужимает картинку через Pillow для уменьшения размера EPUB"""
        if not PIL_AVAILABLE:
            return image_data, 'jpg'

        try:
            img = Image.open(io.BytesIO(image_data))

            if img.mode in ('RGBA', 'P', 'LA'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'RGBA':
                    background.paste(img, mask=img.split()[3])
                else:
                    background.paste(img)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            if img.width > self.max_image_width:
                ratio = self.max_image_width / float(img.width)
                new_height = int((float(img.height) * float(ratio)))
                img = img.resize((self.max_image_width, new_height), Image.Resampling.LANCZOS)

            out_io = io.BytesIO()
            img.save(out_io, format='JPEG', quality=self.image_quality, optimize=True)
            return out_io.getvalue(), 'jpg'
        except Exception as e:
            logger.warning(f"      ⚠️ Не удалось оптимизировать картинку, используем оригинал: {e}")
            return image_data, 'jpg'

    def _download_cover(self, manga_info: Dict, folder_path: Path) -> Optional[str]:
        cover_obj = manga_info.get('cover') or manga_info.get('background') or {}
        url = cover_obj.get('default') if isinstance(cover_obj, dict) else cover_obj

        if not url: return None
        if not url.startswith('http'): url = f"{self.img_url}{url}"

        headers = self.headers.copy()
        headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
            'Referer': 'https://ranobelib.me/',
            'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
        })

        try:
            resp = requests.get(url, headers=headers, verify=False, timeout=10)
            resp.raise_for_status()

            image_data = resp.content
            ext = 'jpg'

            if PIL_AVAILABLE:
                image_data, ext = self._optimize_image_data(image_data)
            else:
                if 'png' in resp.headers.get('content-type', '') or url.endswith('.png'):
                    ext = 'png'

            filename = f"cover.{ext}"
            (folder_path / filename).write_bytes(image_data)
            return filename
        except Exception as e:
            logger.warning(f"Не удалось скачать обложку: {e}")
            return None

    def _save_metadata(self, folder_path: Path, manga_info: Dict, source_url: str, cover_filename: Optional[str]):
        authors = [p.get('name', '').strip() for p in manga_info.get('authors', []) if p.get('name')]
        artists = [p.get('name', '').strip() for p in manga_info.get('artists', []) if p.get('name')]

        meta = {
            "title": self._format_label(manga_info),
            "rus_name": manga_info.get('rus_name'),
            "eng_name": manga_info.get('eng_name'),
            "alternative_titles": manga_info.get('otherNames', []),
            "author": ", ".join(authors) if authors else "Unknown",
            "artist": ", ".join(artists) if artists else "Unknown",
            "description": manga_info.get('summary', '').strip(),
            "source_url": source_url,
            "type": manga_info.get('type', {}).get('label'),
            "country": manga_info.get('type', {}).get('label'),
            "status": manga_info.get('status', {}).get('label'),
            "scanlate_status": manga_info.get('scanlateStatus', {}).get('label'),
            "year": manga_info.get('releaseDate'),
            "release_date_string": manga_info.get('releaseDateString'),
            "chapters_uploaded": manga_info.get('items_count', {}).get('uploaded'),
            "franchise": manga_info.get('franchise', [{}])[0].get('name'),
            "genres": [g.get('name') for g in manga_info.get('genres', [])],
            "tags": [t.get('name') for t in manga_info.get('tags', [])],
            "age_restriction": manga_info.get('ageRestriction', {}).get('label'),
            "publishers": [p.get('name') for p in manga_info.get('publisher', [])],
            "cover_image": cover_filename,
            "language": "ru",
            "rating": manga_info.get('rating', {}).get('average'),
            "views": manga_info.get('views', {}).get('total')
        }

        meta = {k: v for k, v in meta.items() if v is not None}

        meta_path = folder_path / 'metadata.json'
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        logger.info(f"Метаданные сохранены: {meta_path}")

    def _format_label(self, data: Dict) -> str:
        return (data.get('rus_name') or data.get('name') or data.get('eng_name') or 'unknown_ranobe').strip()

    def _init_epub_book(self, manga_info: Dict, source_url: str, cover_filename: Optional[str], save_dir: Path):
        self.epub_book = epub.EpubBook()
        self.epub_book.set_identifier(f"ranobelib-{uuid.uuid4().hex[:12]}")
        title = self._format_label(manga_info)
        self.epub_book.set_title(title)
        self.epub_book.set_language("ru")

        authors_str = ", ".join(p.get('name', '') for p in manga_info.get('authors', [])) or "Неизвестный автор"
        self.epub_book.add_author(authors_str)
        self.epub_book.add_metadata('DC', 'creator', authors_str)

        if summary := manga_info.get('summary'):
            self.epub_book.add_metadata('DC', 'description', summary)

        self.epub_book.add_metadata('DC', 'publisher', 'RanobeLib')
        self.epub_book.add_metadata('DC', 'source', source_url)

        if year := manga_info.get('releaseDate'):
            self.epub_book.add_metadata('DC', 'date', str(year))

        for g in manga_info.get('genres', []):
            if name := g.get('name'):
                self.epub_book.add_metadata('DC', 'subject', name)

        if cover_filename and (cover_path := save_dir / cover_filename).exists():
            with open(cover_path, 'rb') as f:
                self.epub_book.set_cover(f"images/cover.{cover_filename.split('.')[-1]}", f.read(), create_page=True)

        css = epub.EpubItem(
            uid="style_default",
            file_name="style.css",
            media_type="text/css",
            content=(
                "body { font-family: serif; line-height: 1.7; margin: 5% 8%; }\n"
                "h1, h2 { text-align: center; margin: 1.5em 0; }\n"
                "p { margin: 0.8em 0; text-indent: 1.2em; }\n"
                "img { max-width: 100%; height: auto; display: block; margin: 1.5em auto; }\n"
            ).encode("utf-8")
        )
        self.epub_book.add_item(css)

        self.chapter_items = []

    def _add_chapter_to_epub(self, text: str, vol: str, num: str, chapter_title: str,
                             chapter_url: str):
        file_name = f"content/vol_{vol.zfill(2)}_ch_{num.replace('.', '_')}.xhtml"
        c = epub.EpubHtml(title=chapter_title, file_name=file_name, lang="ru")
        c.add_link(href="../style.css", rel="stylesheet", type="text/css")
        c.content = self._text_to_xhtml(chapter_title, text, chapter_url).encode("utf-8")
        self.epub_book.add_item(c)
        self.chapter_items.append(c)

    def _text_to_xhtml(self, chapter_title: str, text: str, chapter_url: str) -> str:
        soup = BeautifulSoup("<html><head></head><body></body></html>", "lxml")
        body = soup.body

        h1 = soup.new_tag("h1")
        h1.string = chapter_title
        body.append(h1)

        for para in [p.strip() for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]:
            p = soup.new_tag("p")
            if "[Image:" in para:
                parts = re.split(r'(\[Image:.*?\])', para)
                for part in parts:
                    if part.startswith("[Image:") and part.endswith("]"):
                        url = part[7:-1].strip()

                        # Встройка картинок
                        local_path = self._embed_image(url, chapter_url)
                        img_src = local_path if local_path else url

                        img = soup.new_tag("img", src=img_src, alt="Иллюстрация")
                        p.append(img)
                    elif part.strip():
                        p.append(part)
            else:
                p.string = para
            body.append(p)

        return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ru" lang="ru">
<head>
    <meta charset="utf-8"/>
    <title>{chapter_title}</title>
    <link rel="stylesheet" href="../style.css" type="text/css"/>
</head>
{str(soup.body)}
</html>'''

    def _embed_image(self, url: str, referer: str) -> Optional[str]:
        if not hasattr(self, 'embedded_images'):
            self.embedded_images = {}

        if url in self.embedded_images:
            return f"../{self.embedded_images[url]}"

        logger.info(f"      ⬇️ Скачивание иллюстрации...")

        # Обход хотлинка - TODO - найти какой-то интереснее способ
        headers = self.headers.copy()
        headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
            'Referer': referer,
            'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
        })

        try:
            resp = requests.get(url, headers=headers, verify=False, timeout=15)
            if resp.status_code == 200:
                image_data = resp.content
                ext = 'jpg'

                if PIL_AVAILABLE:
                    image_data, ext = self._optimize_image_data(image_data)
                else:
                    content_type = resp.headers.get('content-type', '').lower()
                    if 'png' in content_type or url.lower().endswith('.png'):
                        ext = 'png'
                    elif 'webp' in content_type or url.lower().endswith('.webp'):
                        ext = 'webp'
                    elif 'gif' in content_type or url.lower().endswith('.gif'):
                        ext = 'gif'

                img_id = uuid.uuid4().hex[:10]
                file_name = f"images/img_{img_id}.{ext}"

                img_item = epub.EpubItem(
                    uid=f"image_{img_id}",
                    file_name=file_name,
                    media_type=f"image/{'jpeg' if ext == 'jpg' else ext}",
                    content=image_data
                )
                self.epub_book.add_item(img_item)

                self.embedded_images[url] = file_name
                return f"../{file_name}"
            else:
                logger.warning(f"       ⚠️ Не удалось скачать иллюстрацию (код {resp.status_code})")
        except Exception as e:
            logger.warning(f"      ⚠️ Ошибка скачивания иллюстрации: {e}")

        return None

    def _finalize_epub(self, save_dir: Path, title: str):
        if not self.epub_book or not self.chapter_items:
            return

        nav = epub.EpubNav()
        nav.file_name = 'nav.xhtml'
        nav.title = 'Содержание'
        nav.add_link(href='style.css', rel='stylesheet', type='text/css')
        nav.toc = self.chapter_items
        self.epub_book.add_item(nav)
        self.epub_book.add_item(epub.EpubNcx())
        self.epub_book.toc = self.chapter_items

        spine = ['cover'] if self.epub_book.get_item_with_id('cover') else []
        spine += [nav] + self.chapter_items
        self.epub_book.spine = spine

        safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')
        path = save_dir / f"{safe_title}.epub"
        epub.write_epub(str(path), self.epub_book)
        logger.info(f"EPUB сохранён: {path}")


if __name__ == "__main__":
    from utils.setup_logging import setup_logging

    setup_logging()

    parser = argparse.ArgumentParser(description="RanobeLib downloader (txt / epub)")
    parser.add_argument("url", nargs="?", help="URL тайтла")
    parser.add_argument("--format", choices=["txt", "epub"], default="txt")
    parser.add_argument("--images", action="store_true", help="Скачивать иллюстрации и встраивать их прямо в EPUB")
    parser.add_argument("--max-volume", type=int)
    parser.add_argument("--debug", "--debug-requests", action="store_true", help="Показывать все запросы и ответы")

    args = parser.parse_args()

    if not args.url:
        args.url = input("Введите URL тайтла: ").strip()

    if args.url:
        print("--- RanobeLib Pipeline Loader ---")
        loader = RanobeLibLoader(debug_requests=args.debug)

        loader.run(
            url=args.url,
            download_images=args.images,
            max_volume=args.max_volume,
            output_format=args.format
        )
