from jackett_bot import JackettSearchBot

if __name__ == "__main__":
    try:
        bot = JackettSearchBot.initialize("config.env")
    except ValueError as exc:
        print(f"Initialization failed: {exc}")
        print("Please fill the missing values in config.env and start again.")
        raise SystemExit(1) from exc

    bot.run()
