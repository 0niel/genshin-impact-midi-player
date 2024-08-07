import json
import threading
import click
import keyboard
from typing import List, Tuple
from rich.console import Console
from rich.panel import Panel

console = Console()

conversion_cases = {
    "!": "1",
    "@": "2",
    "£": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
}

stored_index: int = 0
playback_speed: float = 1.0
song_data: List[Tuple[float, str]] = []
tempo: float = 1.0
playback_thread: threading.Thread = None
stop_event = threading.Event()


def on_del_press():
    global playback_thread

    if playback_thread is None or not playback_thread.is_alive():
        console.print("[green bold]🎵 Воспроизведение...[/green bold]")
        stop_event.clear()
        playback_thread = threading.Thread(target=play_notes)
        playback_thread.start()


def is_shifted(char_in: str) -> bool:
    ascii_value = ord(char_in)
    return 65 <= ascii_value <= 90 or char_in in '!@#$%^&*()_+{}|:"<>?'


def press_letter(str_letter: str):
    if is_shifted(str_letter):
        if str_letter in conversion_cases:
            str_letter = conversion_cases[str_letter]
        keyboard.release(str_letter.lower())
        keyboard.press("left shift")
        keyboard.press(str_letter.lower())
        keyboard.release("left shift")
    else:
        keyboard.release(str_letter)
        keyboard.press(str_letter)


def release_letter(str_letter: str):
    if is_shifted(str_letter):
        if str_letter in conversion_cases:
            str_letter = conversion_cases[str_letter]
        keyboard.release(str_letter.lower())
    else:
        keyboard.release(str_letter)


def floor_to_zero(value: float) -> float:
    return max(value, 0)


def parse_info(notes: List[Tuple[float, str]]) -> List[Tuple[float, str]]:
    global tempo

    parsed_notes = []
    for i in range(len(notes) - 1):
        note_time = notes[i][0]
        next_note_time = notes[i + 1][0]
        note_duration = (next_note_time - note_time) * (60 / tempo)
        parsed_notes.append((note_duration, notes[i][1]))

    parsed_notes.append((1.0, notes[-1][1]))  # Последнюю ноту держим 1 секунду
    return parsed_notes


def play_notes():
    global stored_index, playback_speed, song_data

    while stored_index < len(song_data) and not stop_event.is_set():
        note_info = song_data[stored_index]
        delay = floor_to_zero(note_info[0]) / playback_speed

        if note_info[1][0] == "~":
            for n in note_info[1][1:]:
                release_letter(n)
        else:
            for n in note_info[1]:
                press_letter(n)
        if "~" not in note_info[1]:
            release_letter(n)
            console.print(
                f"[cyan]{delay:10.2f}[/cyan] [bold magenta]{note_info[1]}[/bold magenta]"
            )

        stored_index += 1
        if delay > 0:
            stop_event.wait(delay)

    if stored_index >= len(song_data):
        stored_index = 0
        console.print("[blue bold]🎶 Песня завершена![/blue bold]")


def rewind():
    global stored_index
    stored_index = max(stored_index - 10, 0)
    console.print(f"[yellow bold]⏪ Перемотано к {stored_index:.2f}[/yellow bold]")


def skip():
    global stored_index
    stored_index += 10
    if stored_index >= len(song_data):
        stored_index = 0
    console.print(f"[yellow bold]⏩ Пропущено к {stored_index:.2f}[/yellow bold]")


def load_song_data(filename: str) -> Tuple[float, List[Tuple[float, str]]]:
    with open(filename, "r") as file:
        data = json.load(file)
        tempo = data.get("tempo", 120)
        notes = data.get("notes", [])
        return tempo, notes


@click.command()
@click.option("--song", "-s", default="song.json", help="Файл с песней в формате JSON.")
@click.option("--speed", "-sp", default=1.0, help="Скорость воспроизведения.")
def main(song: str, speed: float):
    global song_data, playback_speed, tempo
    playback_speed = speed

    tempo, notes = load_song_data(song)
    song_data = parse_info(notes)

    keyboard.hook(on_key_event)

    panel_content = """
    [cyan bold]Воспроизведение/Пауза:[/cyan bold] [green]DELETE[/green]
    [cyan bold]Перемотка назад:[/cyan bold] [yellow]HOME[/yellow]
    [cyan bold]Перемотка вперед:[/cyan bold] [yellow]END[/yellow]
    """
    console.print(
        Panel(
            panel_content,
            title="[bold magenta]Управление[/bold magenta]",
            title_align="left",
            expand=False,
        )
    )

    try:
        while True:
            console.input(
                "[bold]Нажмите [red]Ctrl+C[/red] или закройте окно для выхода[/bold]\n\n"
            )
    except KeyboardInterrupt:
        console.print("[red bold]🚪 Завершение программы[/red bold]")


def on_key_event(event):
    if event.name == "delete":
        on_del_press()
    elif event.name == "home":
        rewind()
    elif event.name == "end":
        skip()


if __name__ == "__main__":
    main()
