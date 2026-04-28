import argparse
import json
import os
import shutil
from pathlib import Path


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def is_leaf_list(node):
    return isinstance(node, list) and all(
        isinstance(item, dict) and "Kostenstelle" in item for item in node
    )


def build_option_label(node, key):
    value = node[key]
    if isinstance(value, dict) and len(value) == 1:
        child_label = next(iter(value))
        return f"{key} — {child_label}"
    return key


def extract_number(label: str):
    import re

    match = re.search(r"#\s*(\d+)", label)
    return int(match.group(1)) if match else float("inf")


def build_leaf_label(item):
    parts = [item.get("Kostenstelle")]
    if item.get("Nummer"):
        parts.append(f"# {item['Nummer']}")
    if item.get("Name"):
        parts.append(item["Name"])
    return " ".join(part for part in parts if part)


def prompt_select(options, prompt_text):
    is_tuples = options and isinstance(options[0], tuple)
    width = len(str(len(options)))
    print(f"\n{prompt_text}")
    for index, option in enumerate(options, start=1):
        label = option[1] if is_tuples else option
        print(f"  {str(index).rjust(width)}. {label}")

    while True:
        choice = input("Nummer eingeben: ").strip()
        if not choice.isdigit():
            print("Bitte eine Zahl aus der Liste eingeben.")
            continue

        index = int(choice)
        if 1 <= index <= len(options):
            return options[index - 1][0] if is_tuples else options[index - 1]

        print("Auswahl außerhalb des gültigen Bereichs. Bitte erneut versuchen.")


def ask_invoice_type():
    options = [
        ("Kreditor", "Kreditor (Rechnung, die wir anderen bezahlen – Eingangsrechnung)"),
        ("Debitor", "Debitor (Rechnung, die andere uns bezahlen – Ausgangsrechnung)"),
    ]
    return prompt_select(options, "Handelt es sich um eine Kreditoren- oder eine Debitoren-Rechnung?")


def ask_company_type():
    options = [
        ("OHG", "OHG"),
        ("GbR", "GbR"),
        ("eG", "eG"),
    ]
    return prompt_select(options, "Welche Rechtsform ist passend für diese Rechnung?")


def ask_paid_status():
    options = [
        ("bezahlt", "bezahlt"),
        ("unbezahlt", "unbezahlt"),
    ]
    return prompt_select(options, "Ist die Rechnung bezahlt?")


def ask_continue():
    while True:
        answer = input("\nMöchtest du eine weitere Rechnung umbenennen? (j/n): ").strip().lower()
        if answer in ("j", "ja"):
            return True
        if answer in ("n", "nein"):
            return False
        print("Bitte 'j' oder 'n' eingeben.")


def traverse(node, prompt_prefix="Wähle Kategorie"):
    if isinstance(node, dict):
        if not node:
            raise ValueError("Empty category node in JSON structure.")

        options = [(key, build_option_label(node, key)) for key in node.keys()]
        options = sorted(options, key=lambda item: extract_number(item[1]))
        choice = prompt_select(options, f"{prompt_prefix}:")
        child = node[choice]

        if isinstance(child, dict):
            if len(child) != 1:
                raise ValueError("Unsupported JSON structure: expected a single subcategory")
            single_key = next(iter(child))
            return [choice, single_key] + traverse(child[single_key], prompt_prefix="Wähle Kostenstelle")

        return [choice] + traverse(child, prompt_prefix="Wähle Kostenstelle")

    if is_leaf_list(node):
        options = [
            (item["Kostenstelle"], build_leaf_label(item), item.get("Nummer"))
            for item in node
        ]
        options = sorted(options, key=lambda item: int(item[2]) if item[2] and str(item[2]).isdigit() else float("inf"))
        options = [(code, label) for code, label, _ in options]
        if not options:
            raise ValueError("No Kostenstelle values found in leaf node.")

        choice = prompt_select(options, "Wähle Kostenstelle:")
        return [choice]

    raise ValueError(f"Unsupported JSON node type: {type(node)}")


def normalize_name_part(value: str):
    return value.replace(" ", "_").replace("/", "_").replace("\\", "_")


def build_output_name(selections, original_name, include_root=False):
    if not include_root and len(selections) > 1:
        selections = selections[1:]
    parts = [normalize_name_part(part) for part in selections if part]
    if not parts:
        raise ValueError("No selection parts available for filename.")

    extension = original_name.suffix
    return Path("_".join(parts) + extension)


def build_output_name_from_metadata(invoice_type, company, paid_status, original_name):
    from datetime import datetime
    import time

    type_name = "Eingangsrechnung" if invoice_type == "Kreditor" else "Ausgangsrechnung"
    now = datetime.now()
    ns = time.time_ns() % 1000
    timestamp = f"{now.strftime('%Y%m%d%H%M%S%f')}{ns:03d}"
    parts = [type_name, company, paid_status, timestamp]
    filename = "_".join(normalize_name_part(part) for part in parts if part)
    return Path(filename + original_name.suffix)


def resolve_unique_destination(dest_path: Path):
    if not dest_path.exists():
        return dest_path

    stem = dest_path.stem
    suffix = dest_path.suffix
    counter = 1
    while True:
        candidate = dest_path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def main():
    parser = argparse.ArgumentParser(
        description="Benenne eine Rechnung nach Rechnungsdaten um: Kreditor/Debitor, Rechtsform und Zahlungsstatus."
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Path to the input file to rename.",
    )
    parser.add_argument(
        "--json",
        default="Kostenstellen.json",
        help="Path to the Kostenstellen.json file (default: Kostenstellen.json in working folder).",
    )
    args = parser.parse_args()

    continue_program = True
    first_run = True
    
    print("\033[32mRechnungswesen Einsortierer\033[0m")
    print("\033[32mAlpha v1.0\033[0m\n\n")
    
    while continue_program:
        if first_run and args.file:
            input_path = Path(args.file).expanduser().resolve()
        else:
            input_path = Path(input("Ziehe die zu behandelnde Datei hierher: ").strip()).expanduser().resolve()

        if not input_path.exists() or not input_path.is_file():
            print(f"Fehler: Datei nicht gefunden: {input_path}")
        else:
            try:
                rechnungstyp = ask_invoice_type()  # Kreditor oder Debitor
                unternehmen = ask_company_type()
                bezahlt = ask_paid_status()

                output_name = build_output_name_from_metadata(rechnungstyp, unternehmen, bezahlt, input_path)
                invoice_folder = "Kreditoren" if rechnungstyp == "Kreditor" else "Debitoren"
                destination_folder = Path(r"\\hokkaido\Daten\UO") / unternehmen / f"{invoice_folder} {unternehmen}"
                destination_folder.mkdir(parents=True, exist_ok=True)
                destination = destination_folder / output_name

                if destination.exists():
                    print(f"\nWarnung: Datei existiert bereits. Überschreiben ist nicht möglich: {destination}")
                else:
                    shutil.copy2(input_path, destination)
                    print(f"\nErfolgreich gespeichert ✅\n{destination}")
            except Exception as exc:
                print(f"Fehler: {exc}")

        first_run = False
        #continue_program = ask_continue()
        print(f"\nDas Programm fährt mit weiteren Rechnungen fort. Wenn du das Programm beenden möchtest, schließe das Fenster.\n")
        if not continue_program:
            print("Fenster schließen, um das Programm zu beenden.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
