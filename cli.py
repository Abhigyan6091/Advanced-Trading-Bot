import typer
from bot.orders import place_order
from bot.strategy import ema_strategy

app = typer.Typer()

@app.command()
def trade(symbol: str, side: str, order_type: str,
          quantity: float, price: float = None, stop: float = None):
    
    result = place_order(symbol, side, order_type, quantity, price, stop)
    typer.echo(result)

@app.command()
def auto(symbol: str = "BTCUSDT", qty: float = 0.001):
    result = ema_strategy(symbol, qty)
    typer.echo(result)

if __name__ == "__main__":
    app()