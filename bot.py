import os
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

# Wczytanie zmiennych środowiskowych z pliku .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Konfiguracja bota i uprawnień
intents = discord.Intents.default()
intents.message_content = True  # Wymagane do odczytywania komend z prefiksem (!)

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Plik bazy danych portfeli
DATA_FILE = Path("portfele.json")
STARTING_BALANCE = 1000
DAILY_REWARD = 500
DAILY_COOLDOWN = 24 * 3600  # 24 godziny w sekundach

# Definicje liczb w ruletce europejskiej (0-36)
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BLACK_NUMBERS = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}
GREEN_NUMBERS = {0}

# ==========================================
# Zarządzanie danymi graczy (JSON)
# ==========================================

def load_data() -> dict:
    """Wczytuje stan portfeli z pliku JSON. Tworzy plik jeśli nie istnieje."""
    if not DATA_FILE.exists():
        save_data({})
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # W razie uszkodzenia pliku tworzymy kopię zapasową i zaczynamy z czystym słownikiem
        backup_name = f"portfele_backup_{int(time.time())}.json"
        try:
            DATA_FILE.rename(backup_name)
            print(f"[OSTRZEŻENIE] Uszkodzony plik portfele.json został zarchiwizowany jako {backup_name}.")
        except Exception:
            pass
        return {}

def save_data(data: dict) -> None:
    """Bezpieczny (atomowy) zapis danych do pliku JSON."""
    temp_file = DATA_FILE.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temp_file.replace(DATA_FILE)

def get_user_data(user_id: int) -> dict:
    """Pobiera dane gracza. Nowy gracz otrzymuje 1000 żetonów na start."""
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "saldo": STARTING_BALANCE,
            "last_daily": 0.0
        }
        save_data(data)
    elif "saldo" not in data[uid]:
        data[uid]["saldo"] = STARTING_BALANCE
        save_data(data)
    return data[uid]

def update_balance(user_id: int, delta: int) -> int:
    """Dodaje lub odejmuje żetony z konta gracza i zwraca nowe saldo."""
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "saldo": STARTING_BALANCE,
            "last_daily": 0.0
        }
    data[uid]["saldo"] = max(0, data[uid].get("saldo", STARTING_BALANCE) + delta)
    save_data(data)
    return data[uid]["saldo"]

def set_daily_timestamp(user_id: int, timestamp: float) -> None:
    """Zapisuje znacznik czasu odebrania nagrody daily."""
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {"saldo": STARTING_BALANCE, "last_daily": timestamp}
    else:
        data[uid]["last_daily"] = timestamp
    save_data(data)

# ==========================================
# Logika Ruletki
# ==========================================

def parse_choice(choice: str):
    """
    Parsuje wybór użytkownika i zwraca znormalizowany typ zakładu oraz wartość:
    (typ_zakladu, nazwa_wyswietlana, mnoznik_zysku)
    """
    choice = choice.lower().strip()

    # Opcje koloru czerwonego
    if choice in ("czerwony", "czerwone", "czerwona", "red", "cz", "r"):
        return ("color", "czerwony", "🔴 Czerwony", 1)  # zysk 1:1 (x2)

    # Opcje koloru czarnego
    if choice in ("czarny", "czarne", "czarna", "black", "c", "b"):
        return ("color", "czarny", "⚫ Czarny", 1)  # zysk 1:1 (x2)

    # Opcje koloru zielonego (czyli 0)
    if choice in ("zielony", "zielone", "zielona", "green", "z", "g"):
        return ("green", 0, "🟢 Zielony (0)", 35)  # zysk 35:1 (x36)

    # Parzyste
    if choice in ("parzyste", "parzysty", "even", "p"):
        return ("parity", "parzyste", "🔢 Parzyste", 1)  # zysk 1:1 (x2)

    # Nieparzyste
    if choice in ("nieparzyste", "nieparzysty", "odd", "np"):
        return ("parity", "nieparzyste", "🔢 Nieparzyste", 1)  # zysk 1:1 (x2)

    # Pojedyncza liczba 0-36
    if choice.isdigit():
        number = int(choice)
        if 0 <= number <= 36:
            color_emoji = "🟢" if number == 0 else ("🔴" if number in RED_NUMBERS else "⚫")
            return ("number", number, f"{color_emoji} Liczba {number}", 35)  # zysk 35:1 (x36)

    return None

def spin_wheel():
    """Losuje liczbę ruletki i zwraca (liczba, kolor, nazwa_koloru, parzystosc_str)."""
    rolled = random.randint(0, 36)
    if rolled == 0:
        color = "zielony"
        color_name = "🟢 Zielony"
        parity = "Brak (zero)"
    elif rolled in RED_NUMBERS:
        color = "czerwony"
        color_name = "🔴 Czerwony"
        parity = "Parzysta" if rolled % 2 == 0 else "Nieparzysta"
    else:
        color = "czarny"
        color_name = "⚫ Czarny"
        parity = "Parzysta" if rolled % 2 == 0 else "Nieparzysta"
    return rolled, color, color_name, parity

def check_win(bet_type, bet_val, rolled, color):
    """Sprawdza czy gracz wygrał dany zakład."""
    if bet_type == "number":
        return rolled == bet_val
    if bet_type == "green":
        return rolled == 0
    if bet_type == "color":
        return color == bet_val
    if bet_type == "parity":
        if rolled == 0:
            return False  # Zero nie jest ani parzyste, ani nieparzyste w ruletce
        if bet_val == "parzyste":
            return rolled % 2 == 0
        if bet_val == "nieparzyste":
            return rolled % 2 != 0
    return False

# ==========================================
# Zdarzenia bota (Events)
# ==========================================

@bot.event
async def on_ready():
    print("=" * 50, flush=True)
    print(f"Zalogowano jako: {bot.user.name}#{bot.user.discriminator} (ID: {bot.user.id})", flush=True)
    print(f"Liczba serwerów: {len(bot.guilds)}", flush=True)
    print("Bot ruletki jest gotowy do gry! Możesz wpisać !saldo, !daily, !ruletka", flush=True)
    print("=" * 50, flush=True)
    await bot.change_presence(activity=discord.Game(name="🎰 !ruletka | !pomoc"))

# ==========================================
# Komendy
# ==========================================

@bot.command(name="saldo", aliases=["stan", "portfel", "kasa", "punkty"])
async def cmd_saldo(ctx, member: discord.Member = None):
    """Sprawdza stan konta gracza."""
    target = member or ctx.author
    data = get_user_data(target.id)
    saldo = data["saldo"]
    last_daily = data.get("last_daily", 0.0)

    # Sprawdzenie statusu daily
    now = time.time()
    time_passed = now - last_daily
    if time_passed >= DAILY_COOLDOWN:
        daily_status = "✅ Dostępne teraz! Wpisz `!daily`"
    else:
        remaining = int(DAILY_COOLDOWN - time_passed)
        godziny = remaining // 3600
        minuty = (remaining % 3600) // 60
        daily_status = f"⏳ Dostępne za: **{godziny}h {minuty}m** (<t:{int(last_daily + DAILY_COOLDOWN)}:R>)"

    embed = discord.Embed(
        title=f"💼 Portfel gracza {target.display_name}",
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc)
    )
    if target.display_avatar:
        embed.set_thumbnail(url=target.display_avatar.url)

    embed.add_field(name="💰 Aktualne saldo", value=f"**{saldo:,}** żetonów".replace(",", " "), inline=False)
    embed.add_field(name="🎁 Nagroda dzienna (!daily)", value=daily_status, inline=False)
    embed.set_footer(text="Kasyno Discord • Zagraj w !ruletka <stawka> <wybór>")

    await ctx.send(embed=embed)

@bot.command(name="daily", aliases=["dzienne", "nagroda"])
async def cmd_daily(ctx):
    """Odbiera 500 darmowych żetonów raz na 24 godziny."""
    data = get_user_data(ctx.author.id)
    last_daily = data.get("last_daily", 0.0)
    now = time.time()
    time_passed = now - last_daily

    if time_passed < DAILY_COOLDOWN:
        remaining = int(DAILY_COOLDOWN - time_passed)
        godziny = remaining // 3600
        minuty = (remaining % 3600) // 60
        sekundy = remaining % 60

        embed = discord.Embed(
            title="⏳ Jeszcze za wcześnie na nagrodę!",
            description=(
                f"Już odebrałeś dzisiejszy bonus.\n"
                f"Kolejne żetony możesz odebrać za: **{godziny} godz. {minuty} min. {sekundy} sek.**\n"
                f"Odblokowanie: <t:{int(last_daily + DAILY_COOLDOWN)}:R>"
            ),
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=f"Aktualne saldo: {data['saldo']} żetonów")
        await ctx.send(embed=embed)
        return

    # Przyznanie nagrody
    new_saldo = update_balance(ctx.author.id, DAILY_REWARD)
    set_daily_timestamp(ctx.author.id, now)

    embed = discord.Embed(
        title="🎁 Odebrano dzienną nagrodę!",
        description=f"Na Twoje konto trafiło **+{DAILY_REWARD}** darmowych żetonów!",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc)
    )
    if ctx.author.display_avatar:
        embed.set_thumbnail(url=ctx.author.display_avatar.url)

    embed.add_field(name="💰 Nowe saldo", value=f"**{new_saldo:,}** żetonów".replace(",", " "), inline=True)
    embed.add_field(name="⏰ Następny odbiór", value=f"<t:{int(now + DAILY_COOLDOWN)}:R>", inline=True)
    embed.set_footer(text="Wykorzystaj żetony w !ruletka!")

    await ctx.send(embed=embed)

@bot.command(name="ruletka", aliases=["roulette", "roll"])
async def cmd_ruletka(ctx, stawka_raw: str = None, *, wybor_raw: str = None):
    """
    Gra w ruletkę europejską.
    Użycie: !ruletka <stawka> <wybór>
    """
    if stawka_raw is None or wybor_raw is None:
        embed = discord.Embed(
            title="ℹ️ Jak zagrać w ruletkę?",
            description=(
                "**Poprawne użycie:**\n"
                "`!ruletka <stawka> <wybór>`\n\n"
                "**Dostępne zakłady:**\n"
                "• `czerwony` / `red` — mnożnik x2 (zysk 1:1)\n"
                "• `czarny` / `black` — mnożnik x2 (zysk 1:1)\n"
                "• `parzyste` / `even` — mnożnik x2 (zysk 1:1)\n"
                "• `nieparzyste` / `odd` — mnożnik x2 (zysk 1:1)\n"
                "• `zielony` / `green` — mnożnik x36 (zysk 35:1)\n"
                "• `0-36` (dowolna liczba) — mnożnik x36 (zysk 35:1)\n\n"
                "**Przykłady:**\n"
                "`!ruletka 100 czerwony`\n"
                "`!ruletka 50 17`\n"
                "`!ruletka all czarny`"
            ),
            color=discord.Color.blurple()
        )
        await ctx.send(embed=embed)
        return

    # Pobieramy dane gracza
    user_data = get_user_data(ctx.author.id)
    saldo = user_data["saldo"]

    # Parsowanie stawki
    stawka_raw = stawka_raw.lower().strip()
    if stawka_raw in ("all", "calosc", "całość", "wszystko", "max"):
        stawka = saldo
    else:
        try:
            stawka = int(stawka_raw)
        except ValueError:
            embed = discord.Embed(
                title="❌ Błędna stawka",
                description="Stawka musi być liczbą dodatnią lub słowem `all`.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return

    if stawka <= 0:
        embed = discord.Embed(
            title="❌ Zbyt mała stawka",
            description="Stawka musi być większa niż 0 żetonów!",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    if stawka > saldo:
        embed = discord.Embed(
            title="❌ Niewystarczające saldo",
            description=(
                f"Nie masz wystarczająco dużo żetonów!\n"
                f"Twój stan konta to **{saldo:,}** żetonów, a próbujesz postawić **{stawka:,}**."
            ).replace(",", " "),
            color=discord.Color.red()
        )
        embed.set_footer(text="Wpisz !daily aby odebrać darmowe żetony!")
        await ctx.send(embed=embed)
        return

    # Parsowanie wyboru gracza
    parsed = parse_choice(wybor_raw)
    if not parsed:
        embed = discord.Embed(
            title="❌ Nieprawidłowy typ zakładu",
            description=(
                f"Nie rozpoznano wyboru: `{wybor_raw}`\n\n"
                "Możesz obstawić:\n"
                "• Kolory: `czerwony` (`red`), `czarny` (`black`), `zielony` (`green`)\n"
                "• Parzystość: `parzyste` (`even`), `nieparzyste` (`odd`)\n"
                "• Konkretną liczbę: od `0` do `36`"
            ),
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    bet_type, bet_val, bet_display, multiplier = parsed

    # Losowanie w ruletce
    rolled, rolled_color, rolled_color_name, rolled_parity = spin_wheel()
    won = check_win(bet_type, bet_val, rolled, rolled_color)

    # Obliczenie wygranej / przegranej i aktualizacja salda
    if won:
        profit = stawka * multiplier
        new_saldo = update_balance(ctx.author.id, profit)
        
        embed = discord.Embed(
            title="🎉 WYGRANA!",
            description=f"Gratulacje {ctx.author.mention}! Fortuna Ci sprzyja!",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(
            name="🎡 Wylosowano",
            value=f"**[{rolled}]** {rolled_color_name} ({rolled_parity})",
            inline=True
        )
        embed.add_field(
            name="🎯 Twój typ",
            value=f"**{bet_display}**",
            inline=True
        )
        embed.add_field(
            name="💵 Postawiono",
            value=f"**{stawka:,}** 🪙".replace(",", " "),
            inline=True
        )
        embed.add_field(
            name="📈 Zysk (mnożnik)",
            value=f"**+{profit:,}** 🪙 (`x{multiplier + 1}`)" .replace(",", " "),
            inline=True
        )
        embed.add_field(
            name="💰 Nowe saldo",
            value=f"**{new_saldo:,}** żetonów".replace(",", " "),
            inline=True
        )
        embed.set_footer(text="Kasyno Discord • Gratulacje!")
    else:
        new_saldo = update_balance(ctx.author.id, -stawka)
        
        embed = discord.Embed(
            title="💥 PRZEGRANA!",
            description=f"Niestety {ctx.author.mention}, tym razem się nie udało.",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(
            name="🎡 Wylosowano",
            value=f"**[{rolled}]** {rolled_color_name} ({rolled_parity})",
            inline=True
        )
        embed.add_field(
            name="🎯 Twój typ",
            value=f"**{bet_display}**",
            inline=True
        )
        embed.add_field(
            name="💵 Strata",
            value=f"**-{stawka:,}** 🪙".replace(",", " "),
            inline=True
        )
        embed.add_field(
            name="💰 Nowe saldo",
            value=f"**{new_saldo:,}** żetonów".replace(",", " "),
            inline=True
        )
        if new_saldo == 0:
            embed.set_footer(text="Zbankrutowałeś! Użyj !daily aby zdobyć darmowe żetony.")
        else:
            embed.set_footer(text="Kasyno Discord • Następnym razem na pewno pójdzie lepiej!")

    if ctx.author.display_avatar:
        embed.set_thumbnail(url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)

@bot.command(name="pomoc", aliases=["help"])
async def cmd_pomoc(ctx):
    """Wyświetla listę dostępnych komend i zasady ruletki."""
    embed = discord.Embed(
        title="🎰 Kasyno Ruletka — Pomoc i Zasady",
        description="Witaj w kasynie Discord! Oto dostępne komendy i instrukcja obstawiania:",
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc)
    )

    embed.add_field(
        name="📜 Dostępne Komendy",
        value=(
            "• `!saldo` — Sprawdza Twój aktualny stan konta i czas do bonusu.\n"
            "• `!saldo @użytkownik` — Sprawdza saldo innego gracza.\n"
            "• `!daily` — Odbiera **500 darmowych żetonów** (raz na 24h).\n"
            "• `!ruletka <stawka> <wybór>` — Gra w ruletkę!\n"
            "• `!pomoc` — Wyświetla to menu pomocy."
        ),
        inline=False
    )

    embed.add_field(
        name="🎯 Typy Zakładów w Ruletce",
        value=(
            "• **Czerwony** (`czerwony` / `red`): Mnożnik **x2** (zysk 1:1)\n"
            "• **Czarny** (`czarny` / `black`): Mnożnik **x2** (zysk 1:1)\n"
            "• **Parzyste** (`parzyste` / `even`): Mnożnik **x2** (zysk 1:1)\n"
            "• **Nieparzyste** (`nieparzyste` / `odd`): Mnożnik **x2** (zysk 1:1)\n"
            "• **Pojedyncza Liczba** (`0` - `36`): Mnożnik **x36** (zysk 35:1)\n"
            "• **Zielony** (`zielony` / `green` / `0`): Mnożnik **x36** (zysk 35:1)"
        ),
        inline=False
    )

    embed.add_field(
        name="💡 Wskazówki",
        value=(
            "• Każdy nowy gracz startuje z **1 000 żetonów**.\n"
            "• Jako stawkę możesz wpisać dokładną liczbę lub `all` (stawia wszystko).\n"
            "• W ruletce europejskiej liczba `0` (zielona) nie jest ani parzysta, ani nieparzysta."
        ),
        inline=False
    )

    embed.set_footer(text="Powodzenia i miłej gry!")
    await ctx.send(embed=embed)

# ==========================================
# Obsługa Błędów
# ==========================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        # Ignorujemy nieistniejące komendy
        return
    if isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="⚠️ Brakujący argument",
            description=f"Wpisz `!pomoc` lub sprawdź poprawne użycie komendy.",
            color=discord.Color.yellow()
        )
        await ctx.send(embed=embed)
        return

    print(f"[BŁĄD] Wystąpił nieoczekiwany błąd: {error}")

# ==========================================
# Uruchomienie Bota
# ==========================================

if __name__ == "__main__":
    if not TOKEN or TOKEN.strip() == "" or TOKEN == "twoj_token_tutaj":
        print("\n" + "!" * 65)
        print("BŁĄD: Nie znaleziono poprawnego tokenu bota w pliku .env!")
        print("1. Otwórz plik .env w edytorze tekstu.")
        print("2. Wpisz swój token bota: DISCORD_TOKEN=twoj_prawdziwy_token")
        print("3. Upewnij się, że włączono 'Message Content Intent' w Discord Developer Portal.")
        print("!" * 65 + "\n")
    else:
        try:
            bot.run(TOKEN)
        except discord.errors.PrivilegedIntentsRequired:
            print("\n" + "=" * 65)
            print("⚠️ BŁĄD UPRAWNIEŃ: Privileged Gateway Intents")
            print("=" * 65)
            print("Bot potrzebuje uprawnienia 'Message Content Intent', aby odczytywać")
            print("komendy tekstowe z prefiksem (!saldo, !daily, !ruletka).")
            print("\nJAK TO WŁĄCZYĆ W 30 SEKUND:")
            print("1. Wejdź na: https://discord.com/developers/applications")
            print("2. Wybierz swoją aplikację bota.")
            print("3. W menu po lewej stronie kliknij zakładkę 'Bot'.")
            print("4. Zjedź w dół do sekcji 'Privileged Gateway Intents'.")
            print("5. Zaznacz: [x] MESSAGE CONTENT INTENT")
            print("6. Kliknij zielony przycisk 'Save Changes' na dole strony.")
            print("7. Uruchom bota ponownie!")
            print("=" * 65 + "\n")
        except discord.errors.LoginFailure:
            print("\n" + "=" * 65)
            print("❌ BŁĄD LOGOWANIA: Podany token w pliku .env jest nieprawidłowy!")
            print("Upewnij się, że skopiowałeś poprawny token bota (Reset Token w zakładce Bot).")
            print("=" * 65 + "\n")
        except Exception as e:
            print(f"\n❌ Wystąpił błąd podczas uruchamiania bota: {e}\n")
