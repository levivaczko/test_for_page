import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageDraw, ImageFont
import os
import math

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("SharePoint Tile Image Generator (4K No-Badge)")
        self.root.geometry("700x750")
        self.root.configure(padx=20, pady=20)
        self.build_ui()

    def build_ui(self):
        row_idx = 0
        
        # --- Background Layers ---
        ttk.Label(self.root, text="1. Háttér Rétegek:", font=("Arial", 10, "bold")).grid(row=row_idx, column=0, sticky="w", pady=(0, 5))
        row_idx += 1
        
        ttk.Label(self.root, text="Alsó réteg (Gradiens háttér):").grid(row=row_idx, column=0, sticky="w")
        self.grad_var = tk.StringVar()
        ttk.Entry(self.root, textvariable=self.grad_var, width=50).grid(row=row_idx+1, column=0, sticky="w")
        ttk.Button(self.root, text="Tallózás", command=lambda: self.browse_file(self.grad_var)).grid(row=row_idx+1, column=1, padx=5)
        row_idx += 2

        ttk.Label(self.root, text="Felső réteg (Kék félkör, átlátszó PNG):").grid(row=row_idx, column=0, sticky="w", pady=(5,0))
        self.shape_var = tk.StringVar()
        ttk.Entry(self.root, textvariable=self.shape_var, width=50).grid(row=row_idx+1, column=0, sticky="w")
        ttk.Button(self.root, text="Tallózás", command=lambda: self.browse_file(self.shape_var)).grid(row=row_idx+1, column=1, padx=5)
        row_idx += 2

        # --- Text Inputs ---
        ttk.Label(self.root, text="2. Szövegek:", font=("Arial", 10, "bold")).grid(row=row_idx, column=0, sticky="w", pady=(15, 5))
        row_idx += 1
        
        ttk.Label(self.root, text="Főcím (Pl: Mermaid diagram generálás):").grid(row=row_idx, column=0, sticky="w")
        self.title_var = tk.StringVar()
        ttk.Entry(self.root, textvariable=self.title_var, width=50).grid(row=row_idx+1, column=0, sticky="w", pady=(0, 5))
        row_idx += 2

        ttk.Label(self.root, text="Alcím (Pl: Langdock):").grid(row=row_idx, column=0, sticky="w")
        self.subtitle_var = tk.StringVar()
        ttk.Entry(self.root, textvariable=self.subtitle_var, width=50).grid(row=row_idx+1, column=0, sticky="w", pady=(0, 10))
        row_idx += 2

        # --- Icons ---
        ttk.Label(self.root, text="3. Ikonok (Max 3 db, átlátszó PNG):", font=("Arial", 10, "bold")).grid(row=row_idx, column=0, sticky="w", pady=(15, 5))
        row_idx += 1
        
        self.icon_vars = [tk.StringVar(), tk.StringVar(), tk.StringVar()]
        for i in range(3):
            ttk.Entry(self.root, textvariable=self.icon_vars[i], width=50).grid(row=row_idx+i, column=0, sticky="w", pady=2)
            ttk.Button(self.root, text="Tallózás", command=lambda v=self.icon_vars[i]: self.browse_file(v)).grid(row=row_idx+i, column=1, padx=5, pady=2)
        row_idx += 3

        # --- Image Formatting (Rounded Corners) ---
        ttk.Label(self.root, text="4. Kép formázása:", font=("Arial", 10, "bold")).grid(row=row_idx, column=0, sticky="w", pady=(15, 5))
        row_idx += 1
        
        self.rounded_var = tk.BooleanVar(value=False)
        self.rounded_cb = tk.Checkbutton(self.root, text="Kerekített sarkok", variable=self.rounded_var, command=self.toggle_radius_input)
        self.rounded_cb.grid(row=row_idx, column=0, sticky="w")
        
        self.radius_frame = ttk.Frame(self.root)
        self.radius_frame.grid(row=row_idx, column=1, sticky="w")
        
        ttk.Label(self.radius_frame, text="Sugár (px):").pack(side="left")
        self.radius_var = tk.StringVar(value="40")
        self.radius_entry = ttk.Entry(self.radius_frame, textvariable=self.radius_var, width=8, state="disabled")
        self.radius_entry.pack(side="left", padx=5)
        row_idx += 1

        # --- Output Filename ---
        ttk.Label(self.root, text="5. Mentés másként (pl. kimenet.jpg vagy kimenet.png):", font=("Arial", 10, "bold")).grid(row=row_idx, column=0, sticky="w", pady=(15, 5))
        self.output_var = tk.StringVar(value="kimenet.jpg")
        ttk.Entry(self.root, textvariable=self.output_var, width=50).grid(row=row_idx+1, column=0, sticky="w")
        row_idx += 2

        # --- Generate Button ---
        generate_btn = tk.Button(self.root, text="KÉP GENERÁLÁSA ÉS MENTÉSE", bg="#005AFA", fg="white", font=("Arial", 12, "bold"), command=self.generate_image)
        generate_btn.grid(row=row_idx, column=0, columnspan=2, pady=25, ipadx=20, ipady=10)

    def browse_file(self, var):
        filename = filedialog.askopenfilename(filetypes=[("Image Files", "*.png *.jpg *.jpeg")])
        if filename: var.set(filename)

    def toggle_radius_input(self):
        if self.rounded_var.get():
            self.radius_entry.config(state="normal")
        else:
            self.radius_entry.config(state="disabled")

    def apply_rounded_corners(self, img, radius):
        w, h = img.size
        temp_factor = 4
        nw, nh = w * temp_factor, h * temp_factor
        nr = radius * temp_factor
        
        mask = Image.new("L", (nw, nh), 0)
        draw = ImageDraw.Draw(mask)
        
        draw.rectangle([0, nr, nw, nh - nr], fill=255)
        draw.rectangle([nr, 0, nw - nr, nh], fill=255)
        draw.pieslice([0, 0, nr * 2, nr * 2], 180, 270, fill=255)
        draw.pieslice([nw - nr * 2, 0, nw, nr * 2], 270, 360, fill=255)
        draw.pieslice([0, nh - nr * 2, nr * 2, nh], 90, 180, fill=255)
        draw.pieslice([nw - nr * 2, nh - nr * 2, nw, nh], 0, 90, fill=255)
        
        mask = mask.resize((w, h), Image.Resampling.LANCZOS)
        img.putalpha(mask)
        return img

    def dynamic_text_wrap_unified(self, draw, text, font, start_x, start_y, shape_img, scale, padding_right, icon_forbidden_zones):
        alpha_pixels = shape_img.getchannel('A').load()
        W, H = shape_img.size
        
        words = text.split()
        current_y = start_y
        
        line_box = draw.textbbox((0,0), "Xy", font=font)
        line_height = (line_box[3]-line_box[1]) + int(12 * scale) 
        
        wrapped_lines = []
        is_clipping = False
        
        while words:
            text_top_y = current_y
            text_bottom_y = current_y + line_height
            check_center_y = current_y + (line_height / 2)
            
            check_y_curve = min(int(check_center_y), H - 1)
            limit_x = W - padding_right 
            
            for x in range(start_x, W):
                if alpha_pixels[x, check_y_curve] < 128: 
                    limit_x = x - padding_right
                    break
            
            for cx, cy, r in icon_forbidden_zones:
                icon_top_y = cy - r
                icon_bottom_y = cy + r
                
                if text_top_y < icon_bottom_y and text_bottom_y > icon_top_y:
                    dy = abs(cy - check_center_y)
                    if dy < r:
                        dx = math.sqrt(r**2 - dy**2)
                        forbidden_horizontal_point = cx - dx
                        limit_point_icons = forbidden_horizontal_point - padding_right
                        limit_x = min(limit_x, limit_point_icons)

            available_width = limit_x - start_x
            
            first_word_bbox = draw.textbbox((0,0), words[0], font=font)
            first_word_width = first_word_bbox[2] - first_word_bbox[0]
            
            if first_word_width > available_width:
                is_clipping = True
            
            current_line = words[0]
            used_words = 1
            for i in range(1, len(words)):
                test_line = current_line + " " + words[i]
                test_bbox = draw.textbbox((0,0), test_line, font=font)
                width_safe = test_bbox[2] - test_bbox[0]
                
                if width_safe <= available_width:
                    current_line = test_line
                    used_words += 1
                else:
                    break
            
            wrapped_lines.append(current_line)
            current_y += line_height
            words = words[used_words:]
            
        return wrapped_lines, is_clipping

    def get_kiss_icon_center(self, alpha_pixels, cy, W, padding_left):
        check_y = int(cy)
        edge_x = W - 1
        for x in range(W-1, padding_left, -1):
            if alpha_pixels[x, check_y] > 128: 
                edge_x = x
                break
        return edge_x

    def generate_image(self):
        try:
            shape_path_orig = self.shape_var.get()
            if not shape_path_orig: return
            shape_orig = Image.open(shape_path_orig).convert("RGBA")
            o_w, o_h = shape_orig.size
            
            basewidth = 1024 
            scale = basewidth / 1000.0
            base_h = int(basewidth * (o_h / o_w)) 
            
            shape = shape_orig.resize((basewidth, base_h), Image.Resampling.LANCZOS)
            grad_path = self.grad_var.get()
            grad_orig = Image.open(grad_path).convert("RGBA")
            grad = grad_orig.resize((basewidth, base_h), Image.Resampling.LANCZOS)

            img = Image.alpha_composite(grad, shape)
            draw = ImageDraw.Draw(img)

            W, H = basewidth, base_h
            padding_left = int(W * 0.08)
            padding_right = int(W * 0.04)
            
            # --- Text Settings ---
            t_text = self.title_var.get()
            initial_title_size_raw = 120
            initial_sub_size_raw = 70  # Exactly 65% smaller base size

            icon_forbidden_zones = []
            i_vars = [f.get() for f in self.icon_vars if f.get() and os.path.exists(f.get())]
            alpha_pixels = shape.getchannel('A').load()
            base_circle_r = int(W * 0.09)

            if len(i_vars) == 1:
                positions_y = [int(H * 0.35)]
            elif len(i_vars) == 2:
                positions_y = [int(H * 0.3), int(H * 0.6)]
            else:
                positions_y = [int(H * 0.25), int(H * 0.5), int(H * 0.75)]
                
            for idx, icon_path in enumerate(i_vars):
                cy = positions_y[idx]
                cx = self.get_kiss_icon_center(alpha_pixels, cy, W, padding_left)
                padded_forbidden_radius = base_circle_r + int(10 * scale)
                icon_forbidden_zones.append((cx, cy, padded_forbidden_radius))

            current_y_title = int(H * 0.12)
            scale_factors = [1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.5, 0.45, 0.4]
            
            final_title_scale = 1.0  # Track the title's final scale
            
            # --- TITLE RENDERING ---
            for scale_factor in scale_factors:
                temp_size = int((initial_title_size_raw * scale_factor) * scale)
                try:
                    t_font = ImageFont.truetype("Koerber-Regular.ttf", temp_size)
                except OSError:
                    try:
                        t_font = ImageFont.truetype("arial.ttf", temp_size)
                    except OSError:
                        t_font = ImageFont.load_default()
                
                temp_wrapped, is_clipping = self.dynamic_text_wrap_unified(
                    draw, t_text, t_font, padding_left, current_y_title, shape, scale, padding_right, icon_forbidden_zones
                )
                
                if not is_clipping:
                    wrapped_title = temp_wrapped
                    final_title_scale = scale_factor  # Save the scale used
                    break
                    
            if 'wrapped_title' not in locals(): wrapped_title = temp_wrapped

            line_box_t = draw.textbbox((0,0), "Xy", font=t_font)
            line_h_t = (line_box_t[3]-line_box_t[1]) + int(12 * scale)
            
            y = current_y_title
            for line in wrapped_title:
                draw.text((padding_left, y), line, fill=(255, 255, 255, 255), font=t_font)
                y += line_h_t
                
            
            # --- SUBTITLE RENDERING ---
            y += int(30 * scale)
            current_y_sub = y
            s_text = self.subtitle_var.get()
            
            if s_text:
                # Apply the exact same scale factor the title ended up using
                temp_size = int((initial_sub_size_raw * final_title_scale) * scale)
                try:
                    s_font = ImageFont.truetype("Koerber-Regular.ttf", temp_size)
                except OSError:
                    try:
                        s_font = ImageFont.truetype("arial.ttf", temp_size)
                    except OSError:
                        s_font = ImageFont.load_default()
                        
                temp_s_wrapped, _ = self.dynamic_text_wrap_unified(
                    draw, s_text, s_font, padding_left, current_y_sub, shape, scale, padding_right, icon_forbidden_zones
                )
                
                wrapped_subtitle = temp_s_wrapped
                
                s_box_final = draw.textbbox((0,0), "Xy", font=s_font)
                line_h_s_final = (s_box_final[3]-s_box_final[1]) + int(10 * scale)
                for s_line in wrapped_subtitle:
                    draw.text((padding_left, y), s_line, fill=(255, 255, 255, 255), font=s_font)
                    y += line_h_s_final

            # --- ICON RENDERING ---
            for cx, cy, padded_forbidden_r in icon_forbidden_zones:
                icon_path = i_vars[icon_forbidden_zones.index((cx,cy, padded_forbidden_r))]
                circle_r = base_circle_r 
                
                mask_factor = 4
                mask_diameter = (circle_r * 2) * mask_factor
                circ_mask = Image.new("RGBA", (mask_diameter, mask_diameter), (0,0,0,0))
                circ_draw_icon = ImageDraw.Draw(circ_mask)
                
                circ_draw_icon.ellipse([0,0, mask_diameter-1, mask_diameter-1], fill=(255,255,255,255))
                circ_img = circ_mask.resize((circle_r*2, circle_r*2), Image.Resampling.LANCZOS)
                
                img.paste(circ_img, (cx - circle_r, cy - circle_r), circ_img)
                
                i_img = Image.open(icon_path).convert("RGBA")
                target_i_size = int(circle_r * 1.2)
                i_img.thumbnail((target_i_size, target_i_size), Image.Resampling.LANCZOS)
                img.paste(i_img, (cx - (i_img.width//2), cy - (i_img.height//2)), i_img)

            # Apply Rounded Corners
            if self.rounded_var.get():
                try:
                    raw_input_radius = int(self.radius_var.get())
                    img = self.apply_rounded_corners(img, int(raw_input_radius * scale))
                except ValueError:
                    messagebox.showwarning("Figyelmeztetés", "Érvénytelen sugár érték (számot adj meg pixelben, pl. 40).")

            # Save
            output_name = self.output_var.get()
            if not output_name.lower().endswith(('.png', '.jpg', '.jpeg')): 
                output_name += '.png' if self.rounded_var.get() else '.jpg'

            if output_name.lower().endswith('.png'):
                img.save(output_name, format="PNG")
            else:
                final_rgb = Image.new("RGB", img.size, (255, 255, 255))
                final_rgb.paste(img, mask=img.split()[3]) 
                final_rgb.save(output_name, quality=100, subsampling=0)
                
            messagebox.showinfo("Kész!", f"A kép sikeresen legenerálva:\n{output_name}")

        except Exception as e: messagebox.showerror("Hiba", f"Váratlan hiba történt:\n{str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()