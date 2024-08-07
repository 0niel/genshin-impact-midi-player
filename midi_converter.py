import os
import click
import json
import subprocess
from rich import print
from rich.prompt import Prompt
from rich.console import Console
from rich.text import Text

console = Console()

class MidiTrackEvent:
    """
    Класс для обработки событий трека MIDI, таких как нажатие и отпускание клавиш, изменение инструмента и т.д.
    """
    type: int = -1
    channel: int = -1

    TYPE_DICT = {
        0x8: "Key Release",         # Отпускание клавиши
        0x9: "Key Press",           # Нажатие клавиши
        0xA: "AfterTouch",          # Послезвучие (нажатие после касания)
        0xB: "Pedal",               # Использование педали
        0xC: "Instrument Change",   # Изменение инструмента
        0xD: "Global AfterTouch",   # Глобальное послезвучие
        0xE: "Pitch Bend"           # Плавное изменение высоты тона
    }

    TYPE_BYTES = {
        0x8: 2,
        0x9: 2,
        0xA: 2,
        0xB: 2,
        0xC: 1,
        0xD: 1,
        0xE: 2
    }


class MidiMetaEvent:
    """
    Класс для обработки мета-событий MIDI, таких как изменение темпа, подписи такта и т.д.
    """
    def __init__(self, offset: int, event_type: int, length: int, data: int):
        self.offset = offset
        self.type = event_type
        self.length = length
        self.data = data


class MidiFile:
    HEADER_OFFSET = 23
    DEFAULT_TEMPO = 120
    VIRTUAL_PIANO_SCALE = "zZxXcvVbBnNmaAsSdfFgGhHjqQwWerRtTyYuqQwWerRtTyYuqQwWerRtTyYu))"
    
    TYPE_DICT = {
        0x00: "Sequence Number",
        0x01: "Text Event",
        0x02: "Copyright Notice",
        0x03: "Sequence/Track Name",
        0x04: "Instrument Name",
        0x05: "Lyric",
        0x06: "Marker",
        0x07: "Cue Point",
        0x20: "MIDI Channel Prefix",
        0x2F: "End of Track",
        0x51: "Set Tempo",
        0x54: "SMTPE Offset",
        0x58: "Time Signature",
        0x59: "Key Signature",
        0x7F: "Sequencer-Specific Meta-event",
        0x21: "Prefix Port",
        0x09: "Other text format [0x09]",
        0x08: "Other text format [0x08]",
        0x0A: "Other text format [0x0A]",
        0x0C: "Other text format [0x0C]"
    }

    def __init__(self, filename: str, default_tempo: int = 120):
        self.filename = filename
        self.bytes = bytearray(open(filename, "rb").read())
        self.header_length = -1
        self.format = -1
        self.tracks = -1
        self.division = -1
        self.division_type = -1
        self.tempo = default_tempo
        self.itr = 0
        self.running_status = -1
        self.running_status_set = False
        self.delta_time = 0
        self.notes = []

        self.start_sequence = [
            [0x4D, 0x54, 0x68, 0x64],  # MThd
            [0x4D, 0x54, 0x72, 0x6B],  # MTrk
            [0xFF]  # FF
        ]
        self.start_counter = [0] * len(self.start_sequence)

        self.read_events()

    def check_start_sequence(self) -> bool:
        """
        Проверяет, начинается ли текущая последовательность байтов с определенной стартовой последовательности (MThd, MTrk или FF).
        """
        return any(len(seq) == count for seq, count in zip(self.start_sequence, self.start_counter))

    def skip(self, i: int):
        self.itr += i

    def read_length(self) -> int:
        """
        Читает длину переменной длины из MIDI-файла.

        MIDI использует "Variable Length Quantity" (VLQ), где старший бит каждого байта указывает на продолжение.
        """
        cont_flag = True
        length = 0
        while cont_flag:
            if (self.bytes[self.itr] & 0x80) >> 7 == 0x1:
                # Если старший бит установлен, продолжаем чтение
                length = (length << 7) + (self.bytes[self.itr] & 0x7F)
            else:
                # Если старший бит не установлен, это последний байт длины
                cont_flag = False
                length = (length << 7) + (self.bytes[self.itr] & 0x7F)
            self.itr += 1
        return length

    def read_mtrk(self):
        """Читает и обрабатывает секцию MTrk (события трека) в MIDI-файле."""
        length = self.get_int(4)
        self.read_midi_track_event(length)

    def read_mthd(self):
        """Читает и обрабатывает секцию MThd (заголовок) в MIDI-файле."""
        self.header_length = self.get_int(4)
        self.format = self.get_int(2)
        self.tracks = self.get_int(2)
        div = self.get_int(2)
        self.division_type = (div & 0x8000) >> 16
        self.division = div & 0x7FFF

    def read_text(self, length: int) -> str:
        text = "".join(chr(self.bytes[i]) for i in range(self.itr, self.itr + length))
        self.itr += length
        return text

    def read_midi_meta_event(self, delta_t: int) -> bool:
        event_type = self.bytes[self.itr]
        self.itr += 1
        length = self.read_length()
        
        event_name = self.TYPE_DICT.get(event_type, f"Неизвестное событие {event_type}")
        if event_type == 0x2F:
            # Конец трека
            self.itr += 2
            return False
        elif event_type in [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0C]:
            # Обработка текстовых событий (например, название трека, текст, метки и т.д.)
            pass
        elif event_type == 0x51:
            self.tempo = round(self.get_int(3) * 0.00024)
        else:
            self.itr += length
        return True

    def read_midi_track_event(self, length: int):
        start = self.itr
        continue_flag = True
        while length > self.itr - start and continue_flag:
            delta_t = self.read_length()
            self.delta_time += delta_t
            if self.bytes[self.itr] == 0xFF:
                # Мета-событие
                self.itr += 1
                continue_flag = self.read_midi_meta_event(delta_t)
            elif 0xF0 <= self.bytes[self.itr] <= 0xF7:
                # Системное событие (сбрасывает состояние running status)
                self.running_status_set = False
                self.running_status = -1
            else:
                # Событие трека (например, нажатие клавиши)
                self.read_voice_event(delta_t)
        self.itr = start + length

    def read_voice_event(self, delta_t: int):
        if self.bytes[self.itr] < 0x80 and self.running_status_set:
            # Используем предыдущее состояние (running status)
            event_type = self.running_status
        else:
            event_type = self.bytes[self.itr]
            if 0x80 <= event_type <= 0xF7:
                # Обновляем running status
                self.running_status = event_type
                self.running_status_set = True
            self.itr += 1

        channel = event_type & 0x0F

        if event_type >> 4 == 0x9:
            # Нажатие клавиши
            key = self.bytes[self.itr]
            self.itr += 1
            velocity = self.bytes[self.itr]
            self.itr += 1

            mapped_key = self.map_key_to_piano(key)
            if velocity > 0:
                # Добавляем ноту, если скорость (velocity) больше нуля
                self.notes.append([self.delta_time / self.division, self.VIRTUAL_PIANO_SCALE[mapped_key]])

        elif event_type >> 4 not in {0x8, 0x9, 0xA, 0xB, 0xD, 0xE}:
            self.itr += 1
        else:
            self.itr += 2

    def map_key_to_piano(self, key: int) -> int:
        mapped_key = key - 36  # Смещаем ноту на 3 октавы вниз, чтобы привести её в диапазон виртуального пианино
        while mapped_key >= len(self.VIRTUAL_PIANO_SCALE):
            mapped_key -= 12  # Если нота выше допустимого диапазона, смещаем её на октаву вниз
        while mapped_key < 0:
            mapped_key += 12  # Если нота ниже допустимого диапазона, смещаем её на октаву вверх
        return mapped_key

    def read_events(self):
        while self.itr + 1 < len(self.bytes):
            for i in range(len(self.start_counter)):
                self.start_counter[i] = 0

            while self.itr + 1 < len(self.bytes) and not self.check_start_sequence():
                for i in range(len(self.start_sequence)):
                    if self.bytes[self.itr] == self.start_sequence[i][self.start_counter[i]]:
                        self.start_counter[i] += 1
                    else:
                        self.start_counter[i] = 0

                if self.itr + 1 < len(self.bytes):
                    self.itr += 1

                if self.start_counter[0] == 4:
                    self.read_mthd()
                elif self.start_counter[1] == 4:
                    self.read_mtrk()

    def get_int(self, size: int) -> int:
        value = 0
        for n in self.bytes[self.itr:self.itr + size]:
            value = (value << 8) + n
        self.itr += size
        return value

    def round_value(self, value: float) -> int:
        return int(value + 1) if value % 1 >= 0.5 else int(value)

    def process_notes(self):
        self.notes.sort()

        i = 1
        while i < len(self.notes):
            if self.notes[i - 1][0] == self.notes[i][0]:
                self.notes[i][1] += self.notes[i - 1][1]
                self.notes.pop(i - 1)
            else:
                i += 1

        for note in self.notes:
            note[1] = "".join(sorted(set(note[1]), key=note[1].index))

        song_data = {
            "tempo": self.tempo,
            "notes": self.notes
        }

        with open("song.json", "w") as song_file:
            json.dump(song_data, song_file, ensure_ascii=False, indent=4)

        self.generate_piano_sheet()

    def generate_piano_sheet(self):
        offset = self.notes[0][0]
        note_count = 0

        with open("sheet.txt", "w") as midi_sheet:
            for note in self.notes:
                note_repr = f"[{note[1]}]" if len(note[1]) > 1 else note[1]
                note_count += 1
                midi_sheet.write(f"{note_repr:>7} ")
                if note_count % 8 == 0:
                    midi_sheet.write("\n")


@click.command()
@click.option(
    "--directory", "-d", default=".", help="Каталог для поиска файлов MIDI."
)
@click.option(
    "--default-tempo", "-t", default=120, help="Темп по умолчанию для обработки MIDI-файлов."
)
@click.option(
    "--play", "-p", is_flag=True, help="Запустить воспроизведение после обработки."
)
def main(directory: str, default_tempo: int, play: bool):
    file_list = os.listdir(directory)
    midi_files = [f for f in file_list if f.endswith(".mid")]

    if not midi_files:
        console.print(":warning: [bold red]MIDI-файлы не найдены в указанном каталоге.[/bold red]")
        return

    console.print("Выберите MIDI файл для обработки:")
    for idx, file in enumerate(midi_files):
        console.print(f"{idx + 1}: {file}")

    choice = Prompt.ask("Введите номер файла для обработки", choices=[str(i+1) for i in range(len(midi_files))], default="1")
    choice = int(choice)

    if choice < 1 or choice > len(midi_files):
        console.print(":warning: [bold red]Неверный выбор.[/bold red]")
        return

    selected_file = os.path.join(directory, midi_files[choice - 1])
    console.print(f":musical_note: [bold green]Обработка {selected_file}...[/bold green]")

    midi = MidiFile(selected_file, default_tempo=default_tempo)
    midi.process_notes()

    console.print(":white_check_mark: [bold blue]Обработка завершена. Проверьте файлы 'song.json' и 'sheet.txt' для вывода.[/bold blue]")

    if play:
        console.print(":play_button: [bold green]Запуск воспроизведения...[/bold green]")
        if os.name == 'nt':
            subprocess.run(["powershell", "-Command", "Start-Process", "python", "-ArgumentList", "'play_song.py', '--song', 'song.json'", "-Verb", "runAs"])
        else:
            subprocess.run(["python", "play_song.py", "--song", "song.json"])

if __name__ == "__main__":
    main()
