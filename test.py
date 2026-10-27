import tkinter as tk
from tkinter import messagebox


class TicTacToe:
    def __init__(self, root):
        self.root = root
        self.root.title("Крестики-нолики")

        # Инициализация состояния игры
        self.current_player = "X"  # Начинает X
        self.board = [""] * 9  # Список из 9 пустых ячеек
        self.buttons = []  # Список объектов кнопок

        self.create_widgets()

    def create_widgets(self):
        """Создание сетки кнопок на экране."""
        for i in range(9):
            # Создаем кнопку для каждой ячейки
            btn = tk.Button(
                self.root,
                text="",
                font=('Arial', 24, 'bold'),
                width=5,
                height=2,
                command=lambda i=i: self.on_click(i)
            )
            # Размещаем кнопки в сетке 3x3
            btn.grid(row=i // 3, column=i % 3)
            self.buttons.append(btn)

        # Кнопка сброса игры
        reset_btn = tk.Button(
            self.root,
            text="Начать заново",
            font=('Arial', 12),
            command=self.reset_game
        )
        reset_btn.grid(row=3, column=0, columnspan=3, sticky="swe")

    def on_click(self, index):
        """Логика нажатия на кнопку мышкой."""
        # Проверяем, пуста ли ячейка и не завершена ли игра
        if self.board[index] == "" and not self.check_winner():
            # Делаем ход
            self.board[index] = self.current_player
            self.buttons[index].config(text=self.current_player,
                                       fg="blue" if self.current_player == "X" else "red")

            # Проверяем условия завершения
            if self.check_winner():
                messagebox.showinfo("Конец игры", f"Игрок {self.current_player} победил!")
                self.disable_all_buttons()
            elif "" not in self.board:
                messagebox.showinfo("Конец игры", "Ничья!")
            else:
                # Передаем ход следующему игроку
                self.current_player = "O" if self.current_player == "X" else "X"

    def check_winner(self):
        """Проверка наличия победителя."""
        win_combinations = [
            (0, 1, 2), (3, 4, 5), (6, 7, 8),  # Горизонтали
            (0, 3, 6), (1, 4, 7), (2, 5, 8),  # Вертикали
            (0, 4, 8), (2, 4, 6)  # Диагонали
        ]
        for combo in win_combinations:
            if self.board[combo[0]] == self.board[combo[1]] == self.board[combo[2]] != "":
                return True
        return False

    def disable_all_buttons(self):
        """Блокирует кнопки после окончания игры."""
        for btn in self.buttons:
            btn.config(state="disabled")

    def reset_game(self):
        """Сброс игры в начальное состояние."""
        self.current_player = "X"
        self.board = [""] * 9
        for btn in self.buttons:
            btn.config(text="", state="normal")


if __name__ == "__main__":
    root = tk.Tk()
    game = TicTacToe(root)
    root.mainloop()
