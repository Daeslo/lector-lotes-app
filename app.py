import streamlit as st
import pandas as pd
import google.generativeai as genai
from PIL import Image
from io import StringIO
import re
import time

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Lector Lotes Produccion", page_icon="🧠", layout="wide")

st.title("🧠 Lector Lotes Produccion")


# --- BARRA LATERAL ---
with st.sidebar:
    st.header("Configuración")
    api_key = st.text_input("Pega aquí tu Google API Key", type="password")

# --- MODELOS (Solo los que existen en tu cuenta) ---
def conseguir_modelos_robustos():
    # Quitamos los 1.5 que te daban Error 404
    return [
        'gemini-2.5-flash',       
        'gemini-2.0-flash-exp'
    ]

# --- COMPRESIÓN ---
def comprimir_imagen(imagen_pil):
    ancho_maximo = 1024 
    if imagen_pil.width > ancho_maximo:
        ratio = ancho_maximo / float(imagen_pil.width)
        altura = int((float(imagen_pil.height) * float(ratio)))
        return imagen_pil.resize((ancho_maximo, altura))
    return imagen_pil

# --- ESPERA VISUAL ---
def esperar_cuenta_atras(segundos, modelo):
    barra = st.progress(0)
    contenedor = st.empty()
    
    # Añadimos un par de segundos extra por seguridad
    tiempo_total = int(segundos) + 2
    
    for i in range(tiempo_total, 0, -1):
        contenedor.warning(f"⏳ Google ({modelo}) está lleno. Reintentando en **{i}** segundos...")
        barra.progress((tiempo_total - i) / tiempo_total)
        time.sleep(1)
        
    contenedor.empty()
    barra.empty()

# --- ANÁLISIS ---
def analizar_con_gemini(imagen_pil, key):
    genai.configure(api_key=key)
    lista_modelos = conseguir_modelos_robustos()
    imagen_optimizada = comprimir_imagen(imagen_pil)
    
    prompt = """
    Analiza esta hoja de producción.
    Extrae tabla con 4 columnas EXACTAS separadas por '|'.
    FORMATO: Proveedor | MaterialOriginal | Lote | Cantidad
    REGLAS:
    1. Cantidad: Solo números (ej: 29000).
    2. Repite Proveedor/Material si hay comillas.
    3. NO uses comas para separar, usa '|'.
    Salida: SOLO los datos.
    """

    errores_detallados = []
    
    # Intentamos con cada modelo
    for nombre_modelo in lista_modelos:
        # Hacemos hasta 3 intentos por modelo si hay saturación
        for intento in range(3): 
            try:
                model = genai.GenerativeModel(nombre_modelo)
                with st.spinner(f"Analizando con {nombre_modelo}..."):
                    response = model.generate_content([prompt, imagen_optimizada], request_options={'timeout': 90})
                    return response.text 
            
            except Exception as e:
                mensaje = str(e)
                # Si es error de Cuota (429), esperamos lo que diga Google
                if "429" in mensaje or "quota" in mensaje.lower():
                    # Intentamos leer si Google nos dice cuántos segundos esperar (ej: "retry in 19.6s")
                    tiempo_espera = 25 # Espera base por defecto
                    match = re.search(r"retry in (\d+)", mensaje)
                    if match:
                        tiempo_espera = int(match.group(1))
                    
                    esperar_cuenta_atras(tiempo_espera, nombre_modelo)
                    continue # Volvemos a intentar el mismo modelo tras la espera
                
                # Si es otro error (como 404 o 500), probamos el siguiente modelo
                errores_detallados.append(f"{nombre_modelo}: {mensaje}")
                break 
    
    # Si todo falla
    raise Exception(f"No se pudo conectar. Detalles: {errores_detallados}")

# --- LIMPIEZA ---
def limpiar_csv(texto):
    if not texto: return ""
    return re.sub(r"```csv|```", "", texto).strip()

def limpiar_num(v):
    try:
        if isinstance(v, str):
            v = v.replace("'", "").replace(" ", "") 
            return float(v.replace(".", "").replace(",", "."))
        return float(v)
    except:
        return 0.0

# --- CATEGORIZACIÓN ---
def categorizar_fila(fila):
    proveedor = str(fila['Proveedor']).lower()
    material = str(fila['MaterialOriginal']).lower()
    lote = str(fila['Lote']).upper().strip()
    
    if "punto" in proveedor or "pack" in proveedor:
        if lote.startswith("P"): return "TAPON"
        if lote.startswith("A"): return "VIAL"
        if "vial" in material: return "VIAL"
        return "TAPON"
    elif "heis" in proveedor:
        if "pild" in material or "frasco" in material: return "PILDORERO"
        if lote.startswith("P"): return "TAPA"
        return "TAPA"
    else:
        if "tapon" in material: return "TAPON"
        if "tapa" in material: return "TAPA"
        if "vial" in material: return "VIAL"
        if lote.startswith("P"): return "TAPA"
        if lote.startswith("A"): return "VIAL"
        return "OTRO"

# --- INTERFAZ ---
uploaded_files = st.file_uploader("Sube tus fotos", type=['jpg','png','jpeg','jfif','webp'], accept_multiple_files=True)

if uploaded_files and st.button("🚀 Procesar Fotos"):
    if not api_key:
        st.error("⚠️ Falta la API Key")
    else:
        todos_los_datos = []
        barra = st.progress(0)
        status = st.empty()
        total = len(uploaded_files)
        
        for i, archivo in enumerate(uploaded_files):
            status.write(f"📸 Procesando {i+1}/{total}: **{archivo.name}**...")
            try:
                img = Image.open(archivo)
                texto_raw = analizar_con_gemini(img, api_key)
                
                if texto_raw:
                    csv_limpio = limpiar_csv(texto_raw)
                    df = pd.read_csv(StringIO(csv_limpio), sep='|', engine='python')
                    df.columns = [c.strip() for c in df.columns]
                    
                    if len(df.columns) >= 4:
                        df.columns = ['Proveedor', 'MaterialOriginal', 'Lote', 'Cantidad'] + list(df.columns[4:])
                        df['Cantidad_Num'] = df['Cantidad'].apply(limpiar_num)
                        df['CATEGORIA'] = df.apply(categorizar_fila, axis=1)
                        todos_los_datos.append(df)
                    else:
                        st.error(f"⚠️ {archivo.name}: Estructura ilegible.")
                else:
                    st.error(f"❌ {archivo.name}: Respuesta vacía.")

            except Exception as e:
                st.error(f"❌ Error en {archivo.name}: {e}")
            
            barra.progress((i + 1) / total)
        
        status.empty()
        barra.empty()
        
        if todos_los_datos:
            df_final = pd.concat(todos_los_datos)
            resumen = df_final.groupby(["CATEGORIA", "Lote"])["Cantidad_Num"].sum().reset_index()
            resumen.columns = ["Categoría", "Lote", "Total Unidades"]
            resumen['Total Unidades'] = resumen['Total Unidades'].apply(lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            
            st.success("✅ ¡Cálculo Completado!")
            st.dataframe(resumen, use_container_width=True)
            
            csv = resumen.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Descargar CSV", csv, "produccion_final.csv", "text/csv")
        else:
            st.warning("No se pudieron extraer datos.")