# This Python file uses the following encoding: utf-8
import sys
import numpy as np
import requests
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QWidget

try:
    from ui_form import Ui_Widget
except ImportError:
    Ui_Widget = None


class PriceFetcherThread(QThread):
    data_ready = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, intent):
        super().__init__()
        self.intent = intent

    def run(self):
        try:
            headers = {"User-Agent": "QuantApp/1.0"}

            spot_url = "https://api.coinbase.com/v2/prices/spot?currency=USD"
            spot_res = requests.get(spot_url, headers=headers, timeout=5).json()
            current_price = float(spot_res["data"]["amount"])

            candle_url = "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600"
            candle_res = requests.get(
                candle_url, headers=headers, timeout=5
            ).json()

            closes = np.array(
                [candle[4] for candle in candle_res[:24]], dtype=np.float64
            )
            mean_price = np.mean(closes)
            std_dev = np.std(closes)

            z_score = (
                (current_price - mean_price) / std_dev if std_dev > 0 else 0.0
            )

            payload = {
                "intent": self.intent,
                "current_price": current_price,
                "mean_price": mean_price,
                "z_score": z_score,
            }
            self.data_ready.emit(payload)

        except Exception as e:
            self.error_signal.emit(str(e))


class BacktestThread(QThread):
    backtest_complete = Signal(dict)
    error_signal = Signal(str)

    def run(self):
        try:
            url = "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400"
            headers = {"User-Agent": "QuantApp/1.0"}
            res = requests.get(url, headers=headers, timeout=5).json()
            closes = np.array([candle[4] for candle in res[:30]][::-1])

            position = 0
            entry_price = 0.0
            total_pnl = 0.0
            trades = 0

            initial_capital = 10000.0
            portfolio_values = [initial_capital]

            for i in range(7, len(closes)):
                window = closes[i - 7 : i]
                mean = np.mean(window)
                std = np.std(window)
                current = closes[i]

                z = (current - mean) / std if std > 0 else 0.0


                if z < -1.0 and position == 0:
                    position = 1
                    entry_price = current
                    trades += 1
                elif z > 1.0 and position == 1:
                    position = 0
                    pnl = current - entry_price
                    total_pnl += pnl
                    trades += 1

                if position == 1:
                    current_portfolio = portfolio_values[-1] + (current - entry_price)
                else:
                    current_portfolio = initial_capital + total_pnl

                portfolio_values.append(current_portfolio)


            portfolio_arr = np.array(portfolio_values)
            daily_returns = np.diff(portfolio_arr) / portfolio_arr[:-1]

            std_return = np.std(daily_returns)
            if std_return > 0:
                sharpe_ratio = (np.mean(daily_returns) / std_return) * np.sqrt(365)
            else:
                sharpe_ratio = 0.0

            peak = np.maximum.accumulate(portfolio_arr)
            drawdowns = (portfolio_arr - peak) / peak
            max_drawdown = np.min(drawdowns) * 100

            payload = {
                "pnl": total_pnl,
                "trades": trades,
                "days": len(closes) - 7,
                "sharpe": sharpe_ratio,
                "max_drawdown": max_drawdown,
            }
            self.backtest_complete.emit(payload)

        except Exception as e:
            self.error_signal.emit(str(e))


class Widget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        if Ui_Widget:
            self.ui = Ui_Widget()
            self.ui.setupUi(self)
        else:
            self.ui = None

        buy_btn = getattr(
            self.ui, "buyButton", getattr(self.ui, "pushButton", None)
        )
        sell_btn = getattr(
            self.ui, "sellButton", getattr(self.ui, "pushButton_2", None)
        )
        backtest_btn = getattr(
            self.ui, "backtestButton", getattr(self.ui, "pushButton_3", None)
        )

        if buy_btn:
            buy_btn.clicked.connect(lambda: self.start_analysis("buy"))
        if sell_btn:
            sell_btn.clicked.connect(lambda: self.start_analysis("sell"))
        if backtest_btn:
            backtest_btn.clicked.connect(self.start_backtest)

    def start_analysis(self, intent):


        self.fetcher = PriceFetcherThread(intent)
        self.fetcher.data_ready.connect(self.handle_analysis_results)
        self.fetcher.error_signal.connect(
            lambda err: self.display_message(
                f"Connection Error: {err}", style="error"
            )
        )
        self.fetcher.start()

    def handle_analysis_results(self, data):
        intent = data["intent"]
        price = data["current_price"]
        z_score = data["z_score"]

        if intent == "buy":
            if z_score > 1.0:
                msg = (
                    f"ANALYSIS: High prices detected.\n"
                    f"Current Price: ${price:,.2f} | Z-Score: +{z_score:.2f}σ.\n"
                    f"Recommendation: HOLD."
                )
                style = "warning"
            elif z_score < -1.0:
                msg = (
                    f"ANALYSIS: Low prices detected.\n"
                    f"Current Price: ${price:,.2f} | Z-Score: {z_score:.2f}σ.\n"
                    f"Recommendation: BUY!"
                )
                style = "success"
            else:
                msg = (
                    f"ANALYSIS: Price within fair-value range.\n"
                    f"Current Price: ${price:,.2f} | Z-Score: {z_score:.2f}σ.\n"
                    f"Recommendation:  HOLD."
                )
                style = "neutral"

        elif intent == "sell":
            if z_score > 1.0:
                msg = (
                    f"ANALYSIS: Profit target reached.\n"
                    f"Current Price: ${price:,.2f} | Z-Score: +{z_score:.2f}σ.\n"
                    f"Recommendation: SELL!"
                )
                style = "success"
            elif z_score < -1.0:
                msg = (
                    f"ANALYSIS: Price depressed below historical mean.\n"
                    f"Current Price: ${price:,.2f} | Z-Score: {z_score:.2f}σ.\n"
                    f"Recommendation: HOLD."
                )
                style = "warning"
            else:
                msg = (
                    f"ANALYSIS: Price within fair-value range.\n"
                    f"Current Price: ${price:,.2f} | Z-Score: {z_score:.2f}σ.\n"
                    f"Recommendation: HOLD."
                )
                style = "neutral"

        self.display_message(msg, style=style)

    def start_backtest(self):
        self.backtester = BacktestThread()
        self.backtester.backtest_complete.connect(self.handle_backtest_results)
        self.backtester.error_signal.connect(
            lambda err: self.display_message(
                f"Backtest Error: {err}", style="error"
            )
        )
        self.backtester.start()

    def handle_backtest_results(self, data):
        pnl = data["pnl"]
        trades = data["trades"]
        days = data["days"]
        sharpe = data["sharpe"]
        mdd = data["max_drawdown"]

        status = "Profitable" if pnl >= 0 else "Unprofitable"
        msg = (
            f"Number of Simulated Days: ({days} ):\n"
            f"• Total Profit: ${pnl:+,.2f} ({status})\n"
            f"• Executed Trades: {trades}\n"
            f"• Sharpe Ratio: {sharpe:.2f}\n"
            f"• Max Drawdown: {mdd:.2f}%"
        )
        style = "success" if pnl >= 0 else "warning"
        self.display_message(msg, style=style)

    def display_message(self, message, style="neutral"):
        try:
            print(message)
        except UnicodeEncodeError:
            print(message.encode("ascii", "replace").decode("ascii"))

        lbl = getattr(self.ui, "textEdit", None)
        if lbl:
            lbl.setPlainText(message)

            styles = {
                "success": (
                    "background-color: #38001e; color: #ff66cc; border-radius: 6px;"
                    " padding: 10px; font-weight: bold;"
                ),
                "warning": (
                    "background-color: #5c0029; color: #ffb3c6; border-radius: 6px;"
                    " padding: 10px; font-weight: bold;"
                ),
                "neutral": (
                    "background-color: #2b1b24; color: #ffc0cb; border-radius: 6px;"
                    " padding: 10px;"
                ),
                "error": (
                    "background-color: #1f0014; color: #ff007f; border-radius: 6px;"
                    " padding: 10px;"
                ),
            }

            lbl.setStyleSheet(styles.get(style, styles["neutral"]))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    widget = Widget()
    widget.show()
    sys.exit(app.exec())