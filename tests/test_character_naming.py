"""Правила переименования персонажей: когда новое имя заменяет текущее, а когда уходит в алиасы."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.data_models import Character, LlmCharacterPatch
from pipelines.character_analysis import CharacterAnalysisPipeline


class TestNameUpgrade(unittest.TestCase):
    def setUp(self):
        self.pipeline = CharacterAnalysisPipeline(MagicMock())
        self.taken = frozenset({"маомао"})

    def check(self, current, new, expected):
        self.assertEqual(self.pipeline._is_name_upgrade(current, new, self.taken), expected, f"{current} -> {new}")

    def test_description_to_real_name(self):
        # Найдено на прогоне тома 1 Кусурии: настоящие имена уходили в алиасы
        self.check("отец Маомао", "Луомен", True)
        self.check("Добродетельная супруга", "Лишу", True)
        self.check("Целомудренная супруга", "А-Дуо", True)

    def test_role_to_name_and_name_extension(self):
        self.check("Служанка", "Сяолан", True)
        self.check("Смит", "Уинстон Смит", True)

    def test_not_an_upgrade(self):
        self.check("Джинши", "Евнух Джинши", False)      # титул к имени — алиас
        self.check("Супруга Гёкуё", "Гёкуё", False)     # то же имя без титула
        self.check("Хоннян", "Доктор", False)           # понижение до роли
        self.check("Старая хозяйка", "бабуля", False)   # обращение, не имя
        self.check("Маомао", "Луомен", False)           # имя на имя — не переименование

    def test_name_taken_by_another_character(self):
        self.check("отец Маомао", "Маомао", False)

    def test_update_renames_and_keeps_old_name_as_alias(self):
        char = Character(id=uuid4(), book_id="b", name="отец Маомао", description="d", spoiler_free_description="d")
        patch = LlmCharacterPatch(name="Луомен", current_chapter_action="Лечит.")
        self.pipeline._update_character(char, patch, "vol_1_chap_7", {}, taken=self.taken)
        self.assertEqual(char.name, "Луомен")
        self.assertIn("отец Маомао", char.aliases)


if __name__ == "__main__":
    unittest.main()
