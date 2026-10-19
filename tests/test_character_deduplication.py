import unittest
from uuid import uuid4
from core.data_models import Character, CharacterArchive, CharacterPatchList, CharacterPatch, CharacterType
from services.embedding_service import EmbeddingService
from services.model_manager import ModelManager
from pipelines.character_analysis import CharacterAnalysisPipeline


class TestCharacterDeduplication(unittest.TestCase):
    def setUp(self):
        self.mm = ModelManager()
        self.pipeline = CharacterAnalysisPipeline(self.mm)

    def test_alias_matching(self):
        """Проверяет, что патч с известным алиасом объединяется с существующим персонажем."""
        archive = CharacterArchive(characters=[
            Character(
                id=uuid4(),
                book_id="test_book",
                name="Джек",
                entity_type=CharacterType.ANIMAL,
                aliases=["Кот Джек", "Рыжий кот"],
                description="Рыжий кот Смита.",
                spoiler_free_description="Рыжий кот."
            )
        ])

        # Патч с именем "Рыжий кот", которое есть в aliases
        patch = CharacterPatch(
            name="Рыжий кот",
            entity_type=CharacterType.ANIMAL,
            description="Тот же рыжий кот на коленях Уинстона.",
            current_chapter_action="Сидит на коленях."
        )
        patch_list = CharacterPatchList(patches=[patch])

        updated = self.pipeline._apply_patch(archive, patch_list, vol=1, chap=3, chapter_text="", book_id="test_book")
        self.assertEqual(len(updated.characters), 1)
        self.assertEqual(updated.characters[0].name, "Джек")
        self.assertIn("vol_1_chap_3", updated.characters[0].chapter_mentions)

    def test_vector_deduplication(self):
        """Проверяет векторное слияние, когда имя не совпадает точно, но семантика идентична."""
        emb_service = self.mm.get_embedding_service()
        
        # Создаем персонажа Джек с вектором
        char1 = Character(
            id=uuid4(),
            book_id="test_book",
            name="Джек",
            entity_type=CharacterType.ANIMAL,
            aliases=["Джек"],
            description="Рыжий пушистый кот проводника Уинстона Смита в поезде.",
            spoiler_free_description="Рыжий кот проводника."
        )
        c1_text = f"{char1.name}. {char1.description}"
        char1.embedding = emb_service.get_embedding(c1_text)

        archive = CharacterArchive(characters=[char1])

        # Кандидат без точного совпадения имени
        patch = CharacterPatch(
            name="Пушистый рыжий комок шерсти",
            entity_type=CharacterType.ANIMAL,
            description="Рыжий пушистый кот проводника Смита, незаконно живущий в поезде.",
            spoiler_free_description="Рыжий кот Смита.",
            current_chapter_action="Мяукает у ног проводника."
        )
        patch_list = CharacterPatchList(patches=[patch])

        updated = self.pipeline._apply_patch(archive, patch_list, vol=1, chap=3, chapter_text="", book_id="test_book")
        
        # Должен остаться 1 персонаж (слияние по вектору)
        self.assertEqual(len(updated.characters), 1)
        self.assertEqual(updated.characters[0].name, "Джек")
        self.assertIn("Пушистый рыжий комок шерсти", updated.characters[0].aliases)


if __name__ == "__main__":
    unittest.main()
