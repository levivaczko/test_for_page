import tkinter as tk
from tkinter import ttk, messagebox
import json
import os

DATA_FILE = 'data.json'

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("SharePoint AI Kártya Kezelő")
        self.root.geometry("1050x650") # Kicsit szélesebb lett, hogy kiférjen a cím
        self.data = self.load_data()
        self.selected_path = None # Stores exactly which item you clicked
        self.build_ui()
        self.refresh_list()

    def load_data(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except: pass
        # Create empty template if no file exists
        return {"altalanos": {"largeCards": [], "smallCards": []}, "copilot": {"largeCards": [], "smallCards": []}}

    def save_data(self):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)

    def build_ui(self):
        # --- Top Table (List of Cards) ---
        list_frame = ttk.LabelFrame(self.root, text="Meglévő Kártyák (Kattints a szerkesztéshez)")
        list_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Hozzáadva a title és isnew oszlop
        columns = ("section", "type", "level", "title", "isnew", "image", "link")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings")
        self.tree.heading("section", text="Szekció")
        self.tree.heading("type", text="Típus")
        self.tree.heading("level", text="Szint")
        self.tree.heading("title", text="Cím (Keresőhöz)")
        self.tree.heading("isnew", text="ÚJ plecsni")
        self.tree.heading("image", text="Kép")
        self.tree.heading("link", text="Link")
        
        # Oszlopok szélességének beállítása
        self.tree.column("section", width=80)
        self.tree.column("type", width=100)
        self.tree.column("level", width=60)
        self.tree.column("title", width=220)
        self.tree.column("isnew", width=80)
        self.tree.column("image", width=180)
        self.tree.column("link", width=150)

        self.tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        # --- Bottom Editor (Form) ---
        form_frame = ttk.LabelFrame(self.root, text="Kártya Szerkesztése / Hozzáadása")
        form_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(form_frame, text="Szekció:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.section_var = tk.StringVar(value="altalanos")
        ttk.Combobox(form_frame, textvariable=self.section_var, values=["altalanos", "copilot"], state="readonly").grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(form_frame, text="Kártya típusa:").grid(row=0, column=2, sticky="w", padx=5, pady=5)
        self.type_var = tk.StringVar(value="smallCards")
        ttk.Combobox(form_frame, textvariable=self.type_var, values=["largeCards", "smallCards"], state="readonly").grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(form_frame, text="Szint:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.level_var = tk.StringVar(value="kezdo")
        ttk.Combobox(form_frame, textvariable=self.level_var, values=["kezdo", "halado"], state="readonly").grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(form_frame, text="Cím (Keresőhöz!):").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.title_entry = ttk.Entry(form_frame, width=50)
        self.title_entry.grid(row=2, column=1, columnspan=3, sticky="w", padx=5, pady=5)

        ttk.Label(form_frame, text="Kép fájlneve:").grid(row=3, column=0, sticky="w", padx=5, pady=5)
        self.img_entry = ttk.Entry(form_frame, width=50)
        self.img_entry.grid(row=3, column=1, columnspan=3, sticky="w", padx=5, pady=5)

        ttk.Label(form_frame, text="Link (Cél URL):").grid(row=4, column=0, sticky="w", padx=5, pady=5)
        self.link_entry = ttk.Entry(form_frame, width=50)
        self.link_entry.grid(row=4, column=1, columnspan=3, sticky="w", padx=5, pady=5)

        self.is_new_var = tk.BooleanVar(value=False)
        self.is_new_cb = tk.Checkbutton(form_frame, text="🔥 Új kártya (Megjelenik rajta az 'ÚJ' plecsni)", variable=self.is_new_var)
        self.is_new_cb.grid(row=5, column=1, columnspan=3, sticky="w", padx=0, pady=5)

        btn_frame = ttk.Frame(form_frame)
        btn_frame.grid(row=6, column=0, columnspan=4, pady=10)

        ttk.Button(btn_frame, text="Új Hozzáadása", command=self.add_card).pack(side="left", padx=5)
        self.btn_update = ttk.Button(btn_frame, text="Kiválasztott Módosítása", command=self.update_card, state="disabled")
        self.btn_update.pack(side="left", padx=5)
        self.btn_delete = ttk.Button(btn_frame, text="Kiválasztott Törlése", command=self.delete_card, state="disabled")
        self.btn_delete.pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Kijelölés Törlése", command=self.clear_form).pack(side="left", padx=5)

    def refresh_list(self):
        # Clear the table
        for row in self.tree.get_children():
            self.tree.delete(row)
        
        # Populate the table from JSON data
        for section, block in self.data.items():
            for ctype, cards in block.items():
                for idx, c in enumerate(cards):
                    iid = f"{section}|{ctype}|{idx}" # Create unique ID
                    is_new_str = "Igen" if c.get("isNew") else "Nem"
                    self.tree.insert("", "end", iid=iid, values=(section, ctype, c.get("level"), c.get("title", ""), is_new_str, c.get("img"), c.get("link")))

    def on_select(self, event):
        # When a user clicks a row, populate the form
        selection = self.tree.selection()
        if not selection: return
        
        iid = selection[0]
        section, ctype, idx = iid.split("|")
        idx = int(idx)
        self.selected_path = (section, ctype, idx)

        card = self.data[section][ctype][idx]
        
        self.section_var.set(section)
        self.type_var.set(ctype)
        self.level_var.set(card.get("level", "kezdo"))
        
        self.title_entry.delete(0, tk.END)
        self.title_entry.insert(0, card.get("title", ""))
        
        self.is_new_var.set(card.get("isNew", False))

        self.img_entry.delete(0, tk.END)
        self.img_entry.insert(0, card.get("img", ""))
        
        self.link_entry.delete(0, tk.END)
        self.link_entry.insert(0, card.get("link", "#"))

        # Enable edit/delete buttons
        self.btn_update.config(state="normal")
        self.btn_delete.config(state="normal")

    def clear_form(self):
        if self.tree.selection():
            self.tree.selection_remove(self.tree.selection())
        self.selected_path = None
        self.title_entry.delete(0, tk.END)
        self.is_new_var.set(False)
        self.img_entry.delete(0, tk.END)
        self.link_entry.delete(0, tk.END)
        self.btn_update.config(state="disabled")
        self.btn_delete.config(state="disabled")

    def get_form_data(self):
        title = self.title_entry.get().strip()
        img = self.img_entry.get().strip()
        link = self.link_entry.get().strip()
        is_new = self.is_new_var.get()
        
        if not title:
            messagebox.showerror("Hiba", "A cím megadása kötelező, különben nem fog működni a kereső!")
            return None

        if not img:
            messagebox.showerror("Hiba", "Kép megadása kötelező!")
            return None
            
        # Automatically fix missing "img/" prefix
        if not img.startswith("img/"):
            img = f"img/{img}"
            
        if not link:
            link = "#"
        # Automatically fix "google.com" to "https://google.com" so it opens correctly
        elif link != "#" and not link.startswith("http") and not link.startswith("/"):
            link = f"https://{link}"

        return {
            "title": title,
            "link": link, 
            "img": img, 
            "level": self.level_var.get(),
            "isNew": is_new
        }

    def add_card(self):
        new_card = self.get_form_data()
        if not new_card: return
        
        sec = self.section_var.get()
        ctype = self.type_var.get()
        self.data[sec][ctype].append(new_card)
        self.save_data()
        self.refresh_list()
        self.clear_form()
        messagebox.showinfo("Siker", "Kártya hozzáadva!")

    def update_card(self):
        if not self.selected_path: return
        updated_card = self.get_form_data()
        if not updated_card: return

        old_sec, old_ctype, idx = self.selected_path
        new_sec = self.section_var.get()
        new_ctype = self.type_var.get()

        # Remove from old spot and add to new spot
        self.data[old_sec][old_ctype].pop(idx)
        self.data[new_sec][new_ctype].append(updated_card)
        
        self.save_data()
        self.refresh_list()
        self.clear_form()
        messagebox.showinfo("Siker", "Kártya módosítva!")

    def delete_card(self):
        if not self.selected_path: return
        if messagebox.askyesno("Megerősítés", "Biztosan törölni szeretnéd ezt a kártyát?"):
            sec, ctype, idx = self.selected_path
            self.data[sec][ctype].pop(idx)
            self.save_data()
            self.refresh_list()
            self.clear_form()

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()