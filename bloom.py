import tkinter as tk
from tkinter import messagebox
import hashlib

# ==========================
# Cấu hình Bloom Filter
# ==========================
SIZE = 20          # Kích thước mảng bit
HASH_COUNT = 3     # Số hàm băm

bit_array = [0] * SIZE

# Chỉ dùng để demo (Bloom Filter thật không lưu dữ liệu này)
items = []


# ==========================
# Hàm băm
# ==========================
def hash_positions(item):
    positions = []

    for i in range(HASH_COUNT):
        text = item + str(i)
        h = hashlib.md5(text.encode()).hexdigest()
        positions.append(int(h, 16) % SIZE)

    return positions


# ==========================
# Cập nhật Bit Array
# ==========================
def update_bits():
    bits.config(text="  ".join(map(str, bit_array)))


# ==========================
# Thêm phần tử
# ==========================
def add_item():
    item = entry.get().strip()

    if item == "":
        messagebox.showwarning("Thông báo", "Vui lòng nhập dữ liệu!")
        return

    pos = hash_positions(item)

    for p in pos:
        bit_array[p] = 1

    # Chỉ để demo
    if item not in items:
        items.append(item)
        listbox.insert(tk.END, item)

    result.config(
        text=f"Đã thêm: {item}\nHash Positions: {pos}",
        fg="green"
    )

    update_bits()


# ==========================
# Kiểm tra phần tử
# ==========================
def check_item():
    item = entry.get().strip()

    if item == "":
        messagebox.showwarning("Thông báo", "Vui lòng nhập dữ liệu!")
        return

    pos = hash_positions(item)

    exist = True

    for p in pos:
        if bit_array[p] == 0:
            exist = False
            break

    if exist:
        result.config(
            text=f"{item} CÓ THỂ tồn tại\nHash Positions: {pos}",
            fg="blue"
        )
    else:
        result.config(
            text=f"{item} CHẮC CHẮN không tồn tại\nHash Positions: {pos}",
            fg="red"
        )

    update_bits()


# ==========================
# Reset
# ==========================
def reset():
    global bit_array

    bit_array = [0] * SIZE

    update_bits()

    result.config(text="")

    entry.delete(0, tk.END)

    items.clear()
    listbox.delete(0, tk.END)


# ==========================
# Giao diện
# ==========================
root = tk.Tk()
root.title("Bloom Filter Demo")
root.geometry("700x500")
root.resizable(False, False)

title = tk.Label(
    root,
    text="Bloom Filter Demo",
    font=("Arial", 18, "bold")
)
title.pack(pady=10)

entry = tk.Entry(
    root,
    width=30,
    font=("Arial", 14)
)
entry.pack()

# Frame chứa các nút
frame = tk.Frame(root)
frame.pack(pady=10)

btn_add = tk.Button(
    frame,
    text="Add",
    width=12,
    bg="green",
    fg="white",
    command=add_item
)
btn_add.grid(row=0, column=0, padx=5)

btn_check = tk.Button(
    frame,
    text="Check",
    width=12,
    bg="dodgerblue",
    fg="white",
    command=check_item
)
btn_check.grid(row=0, column=1, padx=5)

btn_reset = tk.Button(
    frame,
    text="Reset",
    width=12,
    bg="red",
    fg="white",
    command=reset
)
btn_reset.grid(row=0, column=2, padx=5)

# Bit Array
tk.Label(
    root,
    text="Bit Array",
    font=("Arial", 14, "bold")
).pack()

bits = tk.Label(
    root,
    font=("Consolas", 16),
    fg="darkgreen"
)
bits.pack(pady=10)

# Kết quả
result = tk.Label(
    root,
    text="",
    font=("Arial", 13, "bold")
)
result.pack(pady=10)

# Danh sách phần tử
tk.Label(
    root,
    text="Các phần tử đã thêm (Demo)",
    font=("Arial", 13, "bold")
).pack()

listbox = tk.Listbox(
    root,
    width=35,
    height=8,
    font=("Consolas", 12)
)
listbox.pack()

tk.Label(
    root,
    text="*Lưu ý: Bloom Filter thật KHÔNG lưu danh sách này.\nDanh sách chỉ dùng để minh họa trong demo.",
    fg="gray"
).pack(pady=10)

update_bits()

root.mainloop()