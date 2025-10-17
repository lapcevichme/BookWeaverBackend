"""
Утилиты для генерации оптимизированных промптов.
"""
from typing import Type, get_origin, get_args
from pydantic import BaseModel

def generate_human_schema(model: Type[BaseModel], indent: int = 0) -> str:
    """
    Рекурсивно генерирует простое, человекочитаемое описание Pydantic-модели
    для использования в промптах LLM.
    """
    lines = []
    prefix = " " * indent
    for field_name, field_info in model.model_fields.items():
        # Получаем базовый тип поля
        field_type = field_info.annotation
        origin_type = get_origin(field_type)
        type_args = get_args(field_type)

        # Определяем человекочитаемое имя типа
        if origin_type:
            # Для Generic типов вроде List[str] или Optional[str]
            # Optional[X] это Union[X, None]
            if str(origin_type).endswith("Union") and type(None) in type_args:
                 inner_type_name = next(str(t).split('.')[-1].replace("'",'').replace('>','') for t in type_args if t is not type(None))
                 type_name = f"опциональный {inner_type_name}"
            else:
                inner_types = ", ".join(str(t).split('.')[-1].replace("'",'').replace('>','') for t in type_args)
                type_name = f"{origin_type.__name__}[{inner_types}]"
        else:
            type_name = field_type.__name__

        # Формируем строку с описанием
        description = f"({type_name})"
        if field_info.description:
            description += f" - {field_info.description}"

        lines.append(f"{prefix}- `{field_name}` {description}")

        # Рекурсивно обрабатываем вложенные Pydantic-модели
        if type_args:
            # Ищем Pydantic модели внутри List, Optional и т.д.
            for arg in type_args:
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    lines.append(generate_human_schema(arg, indent=indent + 2))

    return "\n".join(lines)
