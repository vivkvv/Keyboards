"""Small async sound playback helper for Windows."""

from __future__ import annotations

from pathlib import Path

import winsound


class SoundPlayer:
    """Play short WAV sounds asynchronously."""

    def play_file(self, sound_path: str) -> bool:
        """Play a WAV file asynchronously if it exists."""
        if not sound_path:
            return False

        path = Path(sound_path)
        if not path.exists() or not path.is_file():
            return False

        try:
            winsound.PlaySound(
                str(path),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except RuntimeError:
            return False
        return True
