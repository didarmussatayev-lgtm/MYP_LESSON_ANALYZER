"""
Синхронизация двух аудиотреков по времени - через ffmpeg + numpy напрямую,
без librosa/soundfile.

Почему так (см. чат, лог с OOM-килом на Railway): librosa на .m4a
откатывается на медленный и прожорливый по памяти путь (audioread), плюс
librosa целиком тянет за собой numba (JIT-компиляция при импорте - сама по
себе заметный расход памяти/времени на старте контейнера) только ради одной
функции загрузки аудио. ffmpeg (уже стоит в Docker-образе, см. Dockerfile)
декодирует .m4a/.aac нативно и эффективно.

Второе экономящее решение: для синхронизации не нужен весь урок целиком -
сдвиг между двумя записями постоянный на всей их длине (оба устройства
пишут в реальном времени, просто стартовали в разные моменты). Поэтому
декодируем только первые duration_sec секунд каждого трека - на порядок
меньше памяти и времени, чем декодировать 40-минutный файл полностью.
"""

from __future__ import annotations

import subprocess

import numpy as np
from scipy.signal import correlate, correlation_lags


def _load_audio_prefix(path: str, sr: int = 4000, duration_sec: float = 180.0) -> np.ndarray:
    """
    Декодирует ПЕРВЫЕ duration_sec секунд аудиофайла в моно, sr Гц, float32,
    напрямую через ffmpeg. Ресемплинг и обрезка по длительности происходят
    во время самого декодирования (флаги -t/-ar/-ac), а не после загрузки
    всего файла в память - в этом и есть экономия.
    """
    cmd = [
        "ffmpeg",
        "-v", "error",
        "-i", path,
        "-t", str(duration_sec),
        "-ac", "1",
        "-ar", str(sr),
        "-f", "f32le",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, check=True)
    audio = np.frombuffer(result.stdout, dtype=np.float32)
    if audio.size == 0:
        raise ValueError(
            f"ffmpeg не смог декодировать аудио из '{path}' (пустой результат). "
            "Проверьте, что файл не повреждён и формат поддерживается ffmpeg."
        )
    return audio


def find_offset_seconds(
    teacher_track_path: str,
    classroom_track_path: str,
    sr: int = 4000,
    duration_sec: float = 180.0,
    max_offset_seconds: float = 120.0,
) -> float:
    """
    Возвращает offset в секундах: на сколько классный трек "опаздывает"
    относительно петличного (положительное число = classroom-трек стартовал
    позже; align.py сдвигает classroom timeline вперёд на эту величину).

    Использует только первые duration_sec секунд каждого трека (см. модуль
    docstring). Если урок начинается длинной тихой паузой/оргмоментом без
    речи учителя - результат может быть неточным, тогда увеличьте
    duration_sec при вызове.

    max_offset_seconds - разумный потолок сдвига (записи не могли начаться
    с разницей в час); если реальный сдвиг больше - скорее всего перепутаны
    файлы, лучше явная ошибка/подозрительное значение, чем тихо неверный
    результат.
    """
    teacher_y = _load_audio_prefix(teacher_track_path, sr=sr, duration_sec=duration_sec)
    classroom_y = _load_audio_prefix(classroom_track_path, sr=sr, duration_sec=duration_sec)

    # Огибающая амплитуды (rectify + сглаживание), не сырой сигнал -
    # устойчивее к разнице в тембре микрофонов.
    def envelope(y: np.ndarray, win: int = 200) -> np.ndarray:
        rect = np.abs(y)
        kernel = np.ones(win) / win
        return np.convolve(rect, kernel, mode="same")

    t_env = envelope(teacher_y)
    c_env = envelope(classroom_y)

    t_env = (t_env - t_env.mean()) / (t_env.std() + 1e-8)
    c_env = (c_env - c_env.mean()) / (c_env.std() + 1e-8)

    corr = correlate(c_env, t_env, mode="full")
    lags = correlation_lags(len(c_env), len(t_env), mode="full")

    max_lag_samples = int(max_offset_seconds * sr)
    mask = np.abs(lags) <= max_lag_samples
    corr = corr[mask]
    lags = lags[mask]

    best_lag = lags[np.argmax(corr)]
    offset_seconds = best_lag / sr
    return float(offset_seconds)


def get_audio_duration_seconds(path: str) -> float:
    """
    Возвращает полную длительность аудиофайла в секундах через ffprobe.
    Нужно для talk-time: проценты считаются от длины ВСЕЙ записи урока,
    а не только от суммарного времени речи (см. align.talk_time_summary
    и обсуждение в чате про то, что тишина = самостоятельная работа
    учеников, а не "нет данных").
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, check=True, text=True)
    return float(result.stdout.strip())


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: python sync.py <teacher_track.m4a> <classroom_track.m4a>")
        sys.exit(1)

    offset = find_offset_seconds(sys.argv[1], sys.argv[2])
    print(f"Classroom track offset relative to teacher track: {offset:.2f} sec")
