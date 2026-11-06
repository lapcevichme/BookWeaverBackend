import unittest
from uuid import uuid4
from core.data_models import Character, CharacterArchive, LlmCharacterPatchList, LlmCharacterPatch, CharacterType
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

        # Кандидат "Рыжий кот" — это алиас существующего персонажа (модель не дала ref)
        patch = LlmCharacterPatch(
            name="Рыжий кот",
            entity_type=CharacterType.ANIMAL,
            description_update="Тот же рыжий кот на коленях Уинстона.",
            current_chapter_action="Сидит на коленях."
        )
        patch_list = LlmCharacterPatchList(patches=[patch])
        refs = self.pipeline._assign_refs(archive.characters)

        self.pipeline._apply_patch(archive, patch_list, refs, [], ["Рыжий кот"], "vol_1_chap_3", "test_book")
        self.assertEqual(len(archive.characters), 1)
        self.assertEqual(archive.characters[0].name, "Джек")
        self.assertIn("vol_1_chap_3", archive.characters[0].chapter_mentions)

    def test_vector_deduplication(self):
        """Векторное сходство не сливает персонажей: только помечается в статистике.

        На Кусурии автослияние по порогу 0.70 склеило 4 пары разных людей
        (docs/experiments/2026-11-06_character-patch.md)."""
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
        patch = LlmCharacterPatch(
            name="Пушистый рыжий комок шерсти",
            entity_type=CharacterType.ANIMAL,
            description_update="Рыжий пушистый кот проводника Смита, незаконно живущий в поезде.",
            current_chapter_action="Мяукает у ног проводника."
        )
        patch_list = LlmCharacterPatchList(patches=[patch])
        refs = self.pipeline._assign_refs(archive.characters)

        self.pipeline._apply_patch(archive, patch_list, refs, [], ["Пушистый рыжий комок шерсти"], "vol_1_chap_3", "test_book")

        # Создан отдельный персонаж, сходство только залогировано
        self.assertEqual(len(archive.characters), 2)
        self.assertEqual(self.pipeline.stats["vector_similar_not_merged"], 1)
        self.assertNotIn("Пушистый рыжий комок шерсти", archive.characters[0].aliases)

if __name__ == "__main__":
    unittest.main()
