import argparse
from rich.console import Console
from rich.status import Status
from bot.client import get_client
from bot.orders import place_futures_order, validate_order

console = Console()

def main():
    parser = argparse.ArgumentParser(prog="TradingBot", description="Binance Futures Bot")
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--side', choices=['BUY', 'SELL'], required=True)
    parser.add_argument('--type', choices=['MARKET', 'LIMIT'], required=True)
    parser.add_argument('--qty', type=float, required=True)
    parser.add_argument('--price', type=float)

    args = parser.parse_args()

    # 1. Enhanced Validation
    is_valid, error_msg = validate_order(args.symbol, args.qty, args.price, args.type)
    if not is_valid:
        console.print(f"[bold red]Validation Error:[/bold red] {error_msg}")
        return

    # 2. Spinner for UX
    with Status(f"[bold green]Placing {args.type} {args.side} on {args.symbol}...", spinner="dots"):
        client = get_client()
        result = place_futures_order(client, args.symbol, args.side, args.type, args.qty, args.price)

    if result:
        console.print("\n[bold green]✅ Order Success![/bold green]")
        console.print(f"ID: [yellow]{result['orderId']}[/yellow] | Status: [cyan]{result['status']}[/cyan]")
    else:
        console.print("\n[bold red]❌ Order Failed.[/bold red] See bot.log.")

if __name__ == "__main__":
    main()