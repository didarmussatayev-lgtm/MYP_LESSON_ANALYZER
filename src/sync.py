"""
Синхронизация двух аудиотреков по времени.

Проблема: петличка учителя и телефон в центре класса почти всегда стартуют
не одновременно (нажали "запись" в разное время). Прежде чем выравнивать
транскрипты по таймкодам (см. align.py), нужно найти сдвиг (offset) между
треками.

Метод: кросс-корреляция понижен-дискретизированных сигналов. Идея простая -
голос учителя присутствует в ОБОИХ треках (в петличке - основной сигнал,
в общем треке - как "утечка"/эхо). Кросс-корреляция находит сдвиг, при
котором сигналы максимально похожи.

Это не идеальный метод (речь учеников в общем треке - шум для корреляции),
но на практике голос учителя обычно доминирует по громкости и это работает
надёжно для урока целиком (correlation по всей длине, а не по секундам).
"""

from __future__ import annotations

import numpy as np
import librosa
from scipy.signal import correlate, correlation_lags


def _load_mono(path: str, sr: int) -> np.ndarray:
    y, _ = librosa.load(path, sr=sr, mono=True)
    return y


def find_offset_seconds(
    teacher_track_path: str,
    classroom_track_path: str,
    sr: int = 4000,
    max_offset_seconds: float = 120.0,
) -> float:
    """
    Возвращает offset в секундах: на сколько классный трек "опаздывает"
    относительно петличного (положительное число = classroom track стартовал
    позже; нужно сдвинуть classroom timeline вперёд на offset, либо сдвинуть
    teacher timeline назад - в align.py используется первый вариант).

    sr=4000 достаточно для кросс-корреляции по огибающей голоса и сильно
    быстрее, чем считать на полной частоте дискретизации.

    max_offset_seconds - на случай, если записи стартовали с разницей больше
    чем разумно (например по ошибке загружен не тот файл) - тогда лучше
    получить explicit warning, чем тихо съехавший результат.
    """
    teacher_y = _load_mono(teacher_track_path, sr)
    classroom_y = _load_mono(classroom_track_path, sr)

    # Используем огибающую амплитуды (rectify + сглаживание), а не сырой
    # сигнал - устойчивее к разнице в тембре микрофонов.
    def envelope(y: np.ndarray, win: int = 200) -> np.ndarray:
        rect = np.abs(y)
        kernel = np.ones(win) / win
        return np.convolve(rect, kernel, mode="same")

    t_env = envelope(teacher_y)
    c_env = envelope(classroom_y)

    # Нормализация, чтобы громкость не искажала корреляцию.
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


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: python sync.py <teacher_track.wav> <classroom_track.wav>")
        sys.exit(1)

    offset = find_offset_seconds(sys.argv[1], sys.argv[2])
    print(f"Classroom track offset relative to teacher track: {offset:.2f} sec")
    print(
        "Если offset положительный - classroom-трек стартовал позже, "
        "align.py сдвинет его timeline на эту величину вперёд."
    )
