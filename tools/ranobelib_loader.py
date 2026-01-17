import logging
import re
import time
import json
import requests
import urllib3
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
import config
logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class RanobeLibLoader:
    """
    Класс для загрузки ранобэ с ranobelib.me и приведения их в формат проекта.
    """

    def __init__(self):
        self.api_url = config.RANOBELIB_API_BASE_URL
        self.img_url = config.RANOBELIB_IMAGE_BASE_URL
        self.headers = config.RANOBELIB_HEADERS.copy()

        if config.RANOBELIB_USER_TOKEN:
            self.headers['Authorization'] = f"Bearer {config.RANOBELIB_USER_TOKEN}"
        else:
            logger.warning("⚠️ RANOBELIB_USER_TOKEN не найден. Доступ к API может быть ограничен.")

        logger.info("RanobeLibLoader инициализирован.")

    def run(self, url: str, output_dir: Optional[Path] = None, download_images: bool = False,
            max_volume: Optional[int] = None):
        """
        Основной метод запуска пайплайна загрузки.
        """
        full_id, numeric_id = self._extract_ids(url)
        if not full_id:
            logger.error(f"Некорректный URL: {url}")
            return

        manga_info = self._fetch_ranobe_data(full_id)
        if not manga_info:
            return

        branches = self._fetch_branches(numeric_id)
        branch_id = self._select_best_branch(branches)
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

        for i, ch in enumerate(chapters):
            vol = ch.get('volume')
            num = ch.get('number')

            if i == 0 or (i + 1) % 5 == 0 or i == total - 1:
                logger.info(f"--> Обработка: Том {vol} Глава {num} ({i + 1}/{total})")

            try:
                data = self._fetch_chapter_content(full_id, vol, num, branch_id)
                if not data:
                    logger.warning(f"Пустой контент: Том {vol} Глава {num}")
                    continue

                text = self._parse_content_node(data.get('content'), data.get('attachments', []), download_images)

                vol_path = save_dir / f"vol_{vol}"
                vol_path.mkdir(exist_ok=True)

                file_path = vol_path / f"chapter_{num}.txt"

                content_to_write = f"{ranobe_title}\nТом {vol} Глава {num}\n\n{text}"
                file_path.write_text(content_to_write, encoding='utf-8')

                time.sleep(0.3)
            except Exception as e:
                logger.error(f"Ошибка при скачивании {vol}-{num}: {e}")

        logger.info("🎉 Загрузка ранобэ завершена!")

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

    def _make_request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        try:
            response = requests.request(
                method,
                url,
                headers=self.headers,
                verify=False,
                timeout=15,
                **kwargs
            )
            response.raise_for_status()
            return response
        except Exception as e:
            logger.error(f"Ошибка запроса {url}: {e}")
            return None

    def _fetch_ranobe_data(self, full_id: str) -> Optional[Dict]:
        url = f"{self.api_url}/manga/{full_id}"

        # Попытка 1
        resp = self._make_request("GET", url)
        if resp:
            data = resp.json().get('data')
            if data: return data

        # Попытка 2
        params = {
            "fields[]": ["eng_name", "name", "summary", "genres", "authors", "releaseDate", "background"]
        }
        resp = self._make_request("GET", url, params=params)
        return resp.json().get('data') if resp else None

    def _fetch_branches(self, numeric_id: str) -> List[Dict]:
        url = f"{self.api_url}/branches/{numeric_id}?team_defaults=1"
        resp = self._make_request("GET", url)
        return resp.json().get('data', []) if resp else []

    def _select_best_branch(self, branches: List[Dict]) -> Optional[int]:
        if not branches: return None
        selected = branches[0]
        team_name = selected['teams'][0].get('name') if selected.get('teams') else "Unknown"
        logger.info(f"Выбрана команда: {team_name} (ID: {selected.get('id')})")
        return selected.get('id')

    def _fetch_chapters(self, full_id: str) -> List[Dict]:
        url = f"{self.api_url}/manga/{full_id}/chapters"
        resp = self._make_request("GET", url)
        if not resp: return []

        chapters = resp.json().get('data', [])
        chapters.sort(key=lambda x: (int(x.get('volume', 0)), float(x.get('number', 0))))
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
            if not img_url.startswith('http'):
                img_url = f"{self.img_url}{img_url}"
            image_map[att['name']] = img_url

        text_parts = []

        def _extract(node):
            if isinstance(node, list):
                for item in node: _extract(item)
                return
            if not isinstance(node, dict): return

            node_type = node.get('type')

            if include_images and node_type == 'image':
                try:
                    attrs = node.get('attrs', {})
                    images_list = attrs.get('images', [])
                    if images_list:
                        image_id = images_list[0].get('image')
                        if image_id in image_map:
                            text_parts.append(f"\n[Image: {image_map[image_id]}]\n")
                except Exception:
                    pass

            if node_type == 'text' and 'text' in node:
                text_parts.append(node['text'])

            if node_type == 'hardBreak':
                text_parts.append('\n')

            if 'content' in node and isinstance(node['content'], list):
                for child in node['content']: _extract(child)
                if node_type == 'paragraph':
                    text_parts.append('\n\n')

        _extract(content_node)
        return re.sub(r'\n{3,}', '\n\n', "".join(text_parts)).strip()

    def _download_cover(self, manga_info: Dict, folder_path: Path) -> Optional[str]:
        cover_obj = manga_info.get('cover') or manga_info.get('background') or {}
        url = cover_obj.get('default') if isinstance(cover_obj, dict) else cover_obj

        if not url: return None
        if not url.startswith('http'): url = f"{self.img_url}{url}"

        headers = {'User-Agent': self.headers['User-Agent'], 'Referer': 'https://ranobelib.me/'}
        try:
            resp = requests.get(url, headers=headers, verify=False, timeout=10)
            resp.raise_for_status()

            ext = 'png' if 'png' in resp.headers.get('content-type', '') or url.endswith('.png') else 'jpg'
            filename = f"cover.{ext}"
            (folder_path / filename).write_bytes(resp.content)
            return filename
        except Exception as e:
            logger.warning(f"Не удалось скачать обложку: {e}")
            return None

    def _save_metadata(self, folder_path: Path, manga_info: Dict, source_url: str, cover_filename: Optional[str]):
        authors = [p.get('name') for p in manga_info.get('authors', [])]
        genres = [g.get('name') for g in manga_info.get('genres', [])]

        meta = {
            "title": self._format_label(manga_info),
            "original_title": manga_info.get('name'),
            "author": ", ".join(authors) if authors else "Unknown",
            "description": manga_info.get('summary'),
            "source_url": source_url,
            "status": manga_info.get('status', {}).get('label'),
            "year": manga_info.get('releaseDate'),
            "tags": genres,
            "cover_image": cover_filename,
            "language": "ru"
        }

        with open(folder_path / 'metadata.json', 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _format_label(self, data: Dict) -> str:
        return data.get('rus_name') or data.get('name') or data.get('eng_name') or 'unknown_ranobe'


if __name__ == "__main__":
    import sys
    from utils.setup_logging import setup_logging
    setup_logging()

    print("--- RanobeLib Pipeline Loader ---")

    target_url = sys.argv[1] if len(sys.argv) > 1 else input("Введите URL тайтла: ").strip()

    if target_url:
        loader = RanobeLibLoader()
        loader.run(target_url, download_images=False)