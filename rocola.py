"""ROCOLA LATINA - ¿De quién es el cover?

Juego de escritorio: suena un cover de música latina y eliges, entre 4
opciones, qué artista o grupo grabó la versión original.
Audio: previews de 30 s de la API pública de Deezer (se guardan en cache/).
Si pones tu propio MP3 en audio/ con el mismo nombre que tendría en cache/
(p. ej. audio/selena_como_flor.mp3), se usa ese archivo en lugar del preview.
Los campos opcionales cover_busqueda_artista / cover_busqueda_titulo del JSON
sirven cuando Deezer publica el cover con otro nombre.
"""
import difflib
import json
import os
import random
import re
import threading
import tkinter as tk
import unicodedata
import urllib.parse
import urllib.request

import pygame

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "cache")
AUDIO = os.path.join(BASE, "audio")
VIDAS = 5
PUNTOS_ACIERTO = 10

BG, FG, ACC, OK, BAD, BTN = "#1b1b2f", "#f0f0f0", "#e43f5a", "#4ecca3", "#e43f5a", "#2e2e4f"


def normalizar(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\(.*?\)", "", s).replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = re.sub(r"\b(the|los|las|el|la)\b", "", s)
    return " ".join(s.split())


def buscar_preview(artista, titulo):
    """Devuelve la URL del preview de Deezer que mejor coincide."""
    datos = []
    # Deezer a veces no responde a la búsqueda exacta; se reintenta con variantes más simples
    for consulta in (f"{artista} {titulo}", f"{normalizar(artista)} {normalizar(titulo)}",
                     f"{normalizar(artista).split()[0]} {normalizar(titulo)}"):
        q = urllib.parse.quote(consulta)
        with urllib.request.urlopen(f"https://api.deezer.com/search?q={q}", timeout=10) as r:
            datos = json.load(r).get("data", [])
        if datos:
            break
    mejor, puntaje = None, 0
    for d in datos:
        if not d.get("preview"):
            continue
        p_art = difflib.SequenceMatcher(None, normalizar(artista), normalizar(d["artist"]["name"])).ratio()
        if p_art < 0.5:  # evita reproducir la canción de otro artista
            continue
        p = p_art + difflib.SequenceMatcher(None, normalizar(titulo), normalizar(d["title"])).ratio()
        if p > puntaje:
            mejor, puntaje = d["preview"], p
    return mejor


def nombre_archivo(artista, titulo):
    return normalizar(f"{artista} {titulo}").replace(" ", "_") + ".mp3"


def obtener_audio(artista, titulo):
    nombre = nombre_archivo(artista, titulo)
    propio = os.path.join(AUDIO, nombre)
    if os.path.exists(propio):
        return propio
    os.makedirs(CACHE, exist_ok=True)
    ruta = os.path.join(CACHE, nombre)
    if not os.path.exists(ruta):
        url = buscar_preview(artista, titulo)
        if not url:
            raise RuntimeError(f"No se encontró audio para {artista} - {titulo}")
        urllib.request.urlretrieve(url, ruta)
    return ruta


def anio(c, tipo):
    a = c.get(f"{tipo}_anio")
    return f" ({a})" if a else ""


class Rocola:
    def __init__(self, root):
        self.root = root
        root.title("ROCOLA LATINA - ¿De quién es el cover?")
        root.configure(bg=BG)
        root.geometry("640x620")
        pygame.mixer.init()
        with open(os.path.join(BASE, "canciones.json"), encoding="utf-8") as f:
            self.canciones = json.load(f)
        self.construir_ui()
        self.nuevo_juego()

    # ---------- UI ----------
    def construir_ui(self):
        lbl = dict(bg=BG, fg=FG)
        tk.Label(self.root, text="🎵 ROCOLA LATINA 🎵", font=("Segoe UI", 26, "bold"), bg=BG, fg=ACC).pack(pady=10)
        self.marcador = tk.Label(self.root, font=("Segoe UI", 14), **lbl)
        self.marcador.pack()
        self.estado = tk.Label(self.root, font=("Segoe UI", 12), wraplength=580, **lbl)
        self.estado.pack(pady=10)

        opciones = tk.Frame(self.root, bg=BG)
        opciones.pack(pady=5)
        self.b_opciones = []
        for i in range(4):
            b = tk.Button(opciones, font=("Segoe UI", 11), width=50, bg=BTN, fg=FG, disabledforeground=FG,
                          activebackground=ACC, relief="flat", command=lambda i=i: self.responder(i))
            b.pack(pady=3)
            self.b_opciones.append(b)

        botones = tk.Frame(self.root, bg=BG)
        botones.pack(pady=10)
        b = dict(font=("Segoe UI", 11, "bold"), width=16, bg=ACC, fg="white", relief="flat")
        self.b_repetir = tk.Button(botones, text="▶ Repetir", command=self.repetir, **b)
        self.b_siguiente = tk.Button(botones, text="⏭ Siguiente", command=self.siguiente_ronda, **b)
        self.b_repetir.grid(row=0, column=0, padx=5)
        self.b_siguiente.grid(row=0, column=1, padx=5)

        self.resultado = tk.Label(self.root, font=("Segoe UI", 13, "bold"), wraplength=580, **lbl)
        self.resultado.pack(pady=8)
        self.info = tk.Label(self.root, font=("Segoe UI", 11, "italic"), wraplength=580, justify="center", **lbl)
        self.info.pack(pady=4)
        self.b_nuevo = tk.Button(self.root, text="🔄 Nuevo juego", command=self.nuevo_juego,
                                 font=("Segoe UI", 11, "bold"), bg=OK, fg=BG, relief="flat")

    def actualizar_marcador(self):
        self.marcador.config(text=f"Puntos: {self.puntos}    Vidas: {'❤' * self.vidas}{'♡' * (VIDAS - self.vidas)}"
                                  f"    Ronda: {self.ronda}/{len(self.canciones)}")

    # ---------- Juego ----------
    def nuevo_juego(self):
        self.puntos, self.vidas, self.ronda = 0, VIDAS, 0
        self.orden = list(range(len(self.canciones)))
        random.shuffle(self.orden)
        self.b_nuevo.pack_forget()
        self.siguiente_ronda()

    def generar_opciones(self, c):
        correcta = c["original_artista"]
        # distractores: artistas originales de otras canciones del catálogo (sin repetir)
        otras = {o["original_artista"] for o in self.canciones if o["original_artista"] != correcta}
        opciones = random.sample(sorted(otras), 3) + [correcta]
        random.shuffle(opciones)
        return opciones

    def siguiente_ronda(self):
        pygame.mixer.music.stop()
        if self.vidas <= 0 or not self.orden:
            return self.fin_juego()
        self.idx = self.orden.pop()
        self.cancion = c = self.canciones[self.idx]
        self.ronda += 1
        self.respondida = False
        self.ruta_cover = self.ruta_original = None
        self.actualizar_marcador()
        self.opciones = self.generar_opciones(c)
        for b, art in zip(self.b_opciones, self.opciones):
            b.config(text=art, state="disabled", bg=BTN)
        self.resultado.config(text="")
        self.info.config(text="")
        self.b_siguiente.config(state="disabled")
        self.b_repetir.config(state="disabled")
        self.estado.config(text="⏳ Cargando cover...")
        self.cargar(c.get("cover_busqueda_artista", c["cover_artista"]),
                    c.get("cover_busqueda_titulo", c["cover_titulo"]), self.al_cargar_cover)

    def cargar(self, artista, titulo, callback):
        def trabajo():
            try:
                ruta = obtener_audio(artista, titulo)
                self.root.after(0, callback, ruta, None)
            except Exception as ex:  # red caída, sin resultados, etc.
                self.root.after(0, callback, None, ex)
        threading.Thread(target=trabajo, daemon=True).start()

    def reproducir(self, ruta):
        pygame.mixer.music.load(ruta)
        pygame.mixer.music.play()

    def al_cargar_cover(self, ruta, error):
        if error:
            self.estado.config(text="⚠ No se pudo cargar el audio, pasando a otra canción...")
            self.ronda -= 1
            self.root.after(1200, self.siguiente_ronda)
            return
        self.ruta_cover = ruta
        self.reproducir(ruta)
        self.estado.config(text="🎧 Escucha este cover... ¿Quién grabó la versión ORIGINAL?")
        for b in self.b_opciones:
            b.config(state="normal")
        self.b_repetir.config(state="normal")

    def repetir(self):
        ruta = self.ruta_original if self.respondida else self.ruta_cover
        if ruta:
            self.reproducir(ruta)

    def responder(self, elegida):
        if self.respondida:
            return
        self.respondida = True
        c = self.cancion
        correcta = self.opciones.index(c["original_artista"])
        if elegida == correcta:
            self.puntos += PUNTOS_ACIERTO
            self.resultado.config(text=f"✅ ¡Correcto! +{PUNTOS_ACIERTO} puntos", fg=OK)
        else:
            self.vidas -= 1
            self.b_opciones[elegida].config(bg=BAD)
            self.resultado.config(text="❌ Incorrecto, pierdes una vida", fg=BAD)
        for b in self.b_opciones:
            b.config(state="disabled")
        self.b_opciones[correcta].config(bg=OK)
        self.actualizar_marcador()
        self.b_repetir.config(state="disabled")
        self.info.config(text=(f"Cover: {c['cover_artista']} – {c['cover_titulo']}{anio(c, 'cover')}\n"
                               f"Original: {c['original_artista']} – {c['original_titulo']}{anio(c, 'original')}\n\n"
                               f"💡 {c.get('dato', '')}"))
        self.estado.config(text="⏳ Cargando la versión original...")
        pygame.mixer.music.stop()
        self.cargar(c["original_artista"], c["original_titulo"], self.al_cargar_original)

    def al_cargar_original(self, ruta, error):
        self.b_siguiente.config(state="normal")
        if self.vidas <= 0 or not self.orden:
            self.b_siguiente.config(text="🏁 Ver resultado")
        if error:
            self.estado.config(text=f"⚠ No se pudo cargar la original ({error})")
            return
        self.ruta_original = ruta
        self.b_repetir.config(state="normal")
        self.reproducir(ruta)
        self.estado.config(text="🎶 Sonando la versión ORIGINAL")

    def fin_juego(self):
        pygame.mixer.music.stop()
        motivo = "Te quedaste sin vidas 💀" if self.vidas <= 0 else "¡Completaste todas las canciones! 🏆"
        self.estado.config(text=f"FIN DEL JUEGO — {motivo}")
        self.resultado.config(text=f"Puntaje final: {self.puntos}", fg=ACC)
        self.info.config(text="")
        for w in [self.b_siguiente, self.b_repetir] + self.b_opciones:
            w.config(state="disabled")
        self.b_siguiente.config(text="⏭ Siguiente")
        self.b_nuevo.pack(pady=10)


if __name__ == "__main__":
    root = tk.Tk()
    Rocola(root)
    root.mainloop()
