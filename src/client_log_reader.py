from pathlib import Path


class ClientLogReader:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

        stat = self.path.stat()
        self._position = stat.st_size
        self._last_mtime_ns = stat.st_mtime_ns
        self._remainder = b""

    def read_new_lines(self) -> list[str]:
        """Read all new lines added to the file.

        Returns:
            list[str]: list of new lines
        """
        try:
            stat = self.path.stat()
        except OSError:
            return []

        truncated = stat.st_size < self._position

        # file didnt change
        if not truncated and stat.st_mtime_ns == self._last_mtime_ns:
            return []

        # In case the file gets truncated (this probably never happens)
        # -> Reset Position to start
        if truncated:
            self._position = 0
            self._remainder = b""

        try:
            with self.path.open("rb") as file:
                file.seek(self._position)
                # file.read(): Read the file from the pointer that was
                # set by seek until the end of the file
                new_bytes = file.read()
                # update the pointer position with the end position
                self._position = file.tell()
        except OSError:
            return []

        self._last_mtime_ns = stat.st_mtime_ns

        if not new_bytes:
            return []

        parts = (self._remainder + new_bytes).split(b"\n")

        # The final part may not be a complete line yet
        self._remainder = parts.pop()

        return [part.rstrip(b"\r").decode("utf-8", errors="replace") for part in parts]
