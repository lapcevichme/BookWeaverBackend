import json
import time
import logging
import config
import csv
from pathlib import Path
from threading import Lock
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)

@dataclass
class LLMMetrics:
    prompt_type: str
    model_name: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    status: str = "success"
    error_message: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

@dataclass
class AudioMetrics:
    entry_id: str
    speaker: str
    text_length: int
    audio_duration_ms: int
    synthesis_latency_ms: float
    rtf: float  # Real-Time Factor
    cer: float
    attempts: int
    status: str = "success" # success, hallucination, error
    timestamp: float = field(default_factory=time.time)

class MetricsCollector:
    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(MetricsCollector, cls).__new__(cls)
                cls._instance._init()
        return cls._instance

    def _init(self):
        self.llm_history: List[LLMMetrics] = []
        self.audio_history: List[AudioMetrics] = []
        self.counters: Dict[str, int] = {
            "json_parse_errors": 0,
            "role_blacklist_triggers": 0,
            "name_collisions": 0,
            "api_retries": 0,
            "tts_hallucinations": 0,
            "tts_retries": 0
        }
        self.active_chapter: Optional[str] = None
        self.chapter_llm_metrics: Dict[str, List[LLMMetrics]] = {}
        self.chapter_audio_metrics: Dict[str, List[AudioMetrics]] = {}
        # Ошибки по главам
        self.chapter_errors: Dict[str, Dict[str, int]] = {}
        
        self.load_from_file(config.LOGS_DIR / "metrics.json")

    def load_from_file(self, file_path: Path):
        if not file_path.exists():
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self.counters = data.get("counters", self.counters)
            self._old_summaries = data.get("chapter_summaries", {})
            self.chapter_errors = data.get("chapter_errors", {})
            
            # Подгружаем историю LLM, если она есть
            for m in data.get("history", {}).get("llm", []):
                self.llm_history.append(LLMMetrics(**m))
            for a in data.get("history", {}).get("audio", []):
                self.audio_history.append(AudioMetrics(**a))
                
            logger.info(f"Metrics: Loaded existing data from {file_path}")
        except Exception as e:
            logger.error(f"Failed to load metrics: {e}")

    def start_chapter(self, chapter_id: str):
        self.active_chapter = chapter_id
        if chapter_id not in self.chapter_llm_metrics:
            self.chapter_llm_metrics[chapter_id] = []
        if chapter_id not in self.chapter_audio_metrics:
            self.chapter_audio_metrics[chapter_id] = []
        logger.debug(f"Metrics: Started tracking chapter {chapter_id}")

    def log_llm_call(self, metrics: LLMMetrics):
        self.llm_history.append(metrics)
        if self.active_chapter:
            self.chapter_llm_metrics[self.active_chapter].append(metrics)
        if metrics.status == "json_error":
            self.increment("json_parse_errors")
        
        if len(self.llm_history) % 5 == 0:
            self.save_to_file(config.LOGS_DIR / "metrics.json")

    def log_audio_gen(self, metrics: AudioMetrics):
        self.audio_history.append(metrics)
        if self.active_chapter:
            self.chapter_audio_metrics[self.active_chapter].append(metrics)
        
        if metrics.status == "hallucination":
            self.increment("tts_hallucinations")
        if metrics.attempts > 1:
            self.increment("tts_retries", metrics.attempts - 1)
            
        logger.debug(f"Metrics: Audio logged for {metrics.entry_id} (RTF: {metrics.rtf:.2f})")
        self.save_to_file(config.LOGS_DIR / "metrics.json")

    def increment(self, counter_name: str, value: int = 1):
        self.counters[counter_name] = self.counters.get(counter_name, 0) + value
        if self.active_chapter:
            if self.active_chapter not in self.chapter_errors:
                self.chapter_errors[self.active_chapter] = {}
            chap_errs = self.chapter_errors[self.active_chapter]
            chap_errs[counter_name] = chap_errs.get(counter_name, 0) + value

    def get_chapter_summary(self, chapter_id: str) -> Dict[str, Any]:
        llm = self.chapter_llm_metrics.get(chapter_id, [])
        audio = self.chapter_audio_metrics.get(chapter_id, [])
        errs = self.chapter_errors.get(chapter_id, {})
        
        if not llm and not audio and hasattr(self, '_old_summaries'):
            summary = self._old_summaries.get(chapter_id, {}).copy()
            summary["errors"] = errs
            return summary

        avg_rtf = sum(a.rtf for a in audio) / len(audio) if audio else 0
        total_audio_sec = sum(a.audio_duration_ms for a in audio) / 1000
        
        return {
            "chapter_id": chapter_id,
            "llm_calls": len(llm),
            "total_tokens": sum(m.input_tokens + m.output_tokens for m in llm),
            "audio_units": len(audio),
            "total_audio_duration_sec": round(total_audio_sec, 2),
            "avg_rtf": round(avg_rtf, 3),
            "avg_cer": round(sum(a.cer for a in audio) / len(audio), 4) if audio else 0,
            "errors": errs
        }

    def generate_report(self) -> str:
        """Генерирует человекочитаемый отчет в формате Markdown"""
        all_chapters = set(self.chapter_llm_metrics.keys())
        if hasattr(self, '_old_summaries'):
            all_chapters.update(self._old_summaries.keys())
        
        report = [
            "# 📊 Отчет по метрикам BookWeaver",
            f"Дата генерации: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
            "## 📈 Глобальные счетчики",
            "| Параметр | Значение |",
            "| :--- | :--- |"
        ]
        for k, v in self.counters.items():
            report.append(f"| {k} | {v} |")
        
        report.append("\n## 📖 Статистика по главам")
        report.append("| Глава | Токены | Audio | CER | Ошибки (JSON/Coll/TTS) |")
        report.append("| :--- | :---: | :---: | :---: | :--- |")
        
        total_tokens = 0
        total_audio_duration = 0
        
        for cid in sorted(all_chapters):
            s = self.get_chapter_summary(cid)
            e = s.get("errors", {})
            err_str = f"J:{e.get('json_parse_errors',0)} / C:{e.get('name_collisions',0)} / H:{e.get('tts_hallucinations',0)}"
            
            report.append(f"| {cid} | {s.get('total_tokens', 0)} | {s.get('total_audio_duration_sec', 0)}s | {s.get('avg_cer', 0)} | {err_str} |")
            total_tokens += s.get('total_tokens', 0)
            total_audio_duration += s.get('total_audio_duration_sec', 0)

        report.append(f"\n**ИТОГО:**")
        report.append(f"- **Всего токенов:** {total_tokens}")
        report.append(f"- **Общая длительность аудио:** {round(total_audio_duration / 60, 2)} мин")
        
        return "\n".join(report)

    def export_to_csv(self, file_path: Path):
        """Экспорт сводки по главам в CSV для Pandas"""
        all_chapters = set(self.chapter_llm_metrics.keys())
        if hasattr(self, '_old_summaries'):
            all_chapters.update(self._old_summaries.keys())
            
        fieldnames = [
            "chapter_id", "llm_calls", "total_tokens", "audio_units", 
            "total_audio_duration_sec", "avg_rtf", "avg_cer",
            "json_parse_errors", "name_collisions", "tts_hallucinations"
        ]
        
        try:
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for cid in sorted(all_chapters):
                    s = self.get_chapter_summary(cid)
                    e = s.get("errors", {})
                    row = {k: s.get(k, 0) for k in fieldnames if k != "chapter_id"}
                    row["chapter_id"] = cid
                    row["json_parse_errors"] = e.get("json_parse_errors", 0)
                    row["name_collisions"] = e.get("name_collisions", 0)
                    row["tts_hallucinations"] = e.get("tts_hallucinations", 0)
                    writer.writerow(row)
        except Exception as e:
            logger.error(f"Failed to export CSV: {e}")

    def save_to_file(self, file_path: Path):
        all_chapter_ids = set(self.chapter_llm_metrics.keys())
        if hasattr(self, '_old_summaries'):
            all_chapter_ids.update(self._old_summaries.keys())
            
        summaries = {cid: self.get_chapter_summary(cid) for cid in all_chapter_ids}

        data = {
            "counters": self.counters,
            "chapter_summaries": summaries,
            "chapter_errors": self.chapter_errors,
            "history": {
                "llm": [asdict(m) for m in self.llm_history],
                "audio": [asdict(m) for m in self.audio_history]
            }
        }
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # Отчеты
            self.export_to_csv(file_path.parent / "metrics.csv")
            report_path = file_path.parent / "metrics_report.md"
            report_path.write_text(self.generate_report(), encoding="utf-8")
            
        except Exception as e:
            logger.error(f"❌ Failed to save metrics: {e}")

metrics_collector = MetricsCollector()
