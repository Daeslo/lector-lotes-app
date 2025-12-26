import streamlit as st
import pandas as pd
import google.generativeai as genai
from PIL import Image
from io import StringIO
import re
import time

# --- CONFIGURACIÓN PARA MÓVIL (ICONO CAMBIADO) ---
st.set_page_config(page_title="Lector de Lotes", page_icon="🧮", layout="wide")

st.title("🧮 Lector de Lotes")


# --- BARRA LATERAL ---
with st.sidebar:
    st.header("Configuración")
    api_key = st.text_input("Pega aquí tu Google API Key", type="password")

# --- MODELOS ---
def conseguir_modelos_robustos():
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
    tiempo_total = int(segundos) + 2
    for i in range(tiempo_total, 0, -1):
        contenedor.warning(f"⏳ Google ({modelo}) saturado. Esperando {i}s...")
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
    Analiza esta hoja de producción manuscrita.
    Extrae tabla con 4 columnas EXACTAS separadas por '|'.
    FORMATO: Proveedor | MaterialOriginal | Lote | Cantidad
    
    REGLAS CRÍTICAS:
    1. Cantidad: Columna 'Uds. Usadas'. Copia el número TAL CUAL lo ves (con puntos y comas).
       - Ejemplo: Si ves "29.000", escribe "29.000".
       - Ejemplo: Si ves "2.3", escribe "2.3".
    2. Lote: Copia el código alfanumérico.
    3. Material: Copia el texto.
    4. Rellena huecos: Si hay comillas o vacío, repite el valor de arriba.
    
    Salida: SOLO los datos CSV.
    """

    errores_detallados = []
    
    for nombre_modelo in lista_modelos:
        for intento in range(3): 
            try:
                model = genai.GenerativeModel(nombre_modelo)
                with st.spinner(f"Procesando con {nombre_modelo}..."):
                    response = model.generate_content([prompt, imagen_optimizada], request_options={'timeout': 90})
                    return response.text 
            except Exception as e:
                mensaje = str(e)
                if "429" in mensaje or "quota" in mensaje.lower():
                    tiempo_espera = 25
                    match = re.search(r"retry in (\d+)", mensaje)
                    if match: tiempo_espera = int(match.group(1))
                    esperar_cuenta_atras(tiempo_espera, nombre_modelo)
                    continue 
                errores_detallados.append(f"{nombre_modelo}: {mensaje}")
                break 
    raise Exception(f"Error: {errores_detallados}")

# --- LIMPIEZA ---
def limpiar_csv(texto):
    if not texto: return ""
    return re.sub(r"```csv|```", "", texto).strip()

# --- 🛠️ LA SOLUCIÓN MATEMÁTICA (REGEX) ---
def limpiar_num(v):
    try:
        v = str(v).replace("'", "").strip()
        
        # REGLA DE ORO: Si hay un punto seguido de 3 números (ej: 29.000), ES UN MIL.
        # Usamos Expresiones Regulares para detectarlo con seguridad.
        if re.search(r'\d+\.\d{3}', v):
            v = v.replace(".", "") # Borramos el punto: 29.000 -> 29000
            
        # Si queda alguna coma, la convertimos a punto decimal
        v = v.replace(",", ".")
        
        return float(v)
    except:
        return 0.0

# --- CATEGORIZACIÓN ---
def categorizar_fila(fila):
    proveedor = str(fila['Proveedor']).lower()
    material = str(fila['MaterialOriginal']).lower()
    lote = str(fila['Lote']).upper().strip()
    
    # Prioridad al texto del material
    if "tapon" in material or "tapón" in material or "negro" in material: return "TAPON"
    if "vial" in material or "ambar" in material: return "VIAL"
    if "pild" in material or "frasco" in material: return "PILDORERO"
    if "tapa" in material: return "TAPA"

    # Reglas secundarias
    if "punto" in proveedor or "pack" in proveedor:
        if lote.startswith("P"): return "TAPON"
        if lote.startswith("A"): return "VIAL"
        return "TAPON"
    elif "heis" in proveedor: return "TAPA"
        
    if lote.startswith("P"): return "TAPON"
    if lote.startswith("A"): return "VIAL"
    return "OTRO"

# --- INTERFAZ ---
col1, col2 = st.columns(2)
with col1:
    st.write("📸 **Cámara**")
    foto_camara = st.camera_input("Toma foto", label_visibility="collapsed")
with col2:
    st.write("📂 **Galería**")
    archivos_subidos = st.file_uploader("Sube fotos", type=['jpg','png','jpeg','webp'], accept_multiple_files=True, label_visibility="collapsed")

lista_imagenes = []
if foto_camara: lista_imagenes.append(foto_camara)
if archivos_subidos: lista_imagenes.extend(archivos_subidos)

if lista_imagenes and st.button("🚀 CALCULAR AHORA", use_container_width=True, type="primary"):
    if not api_key:
        st.error("⚠️ Falta API Key")
    else:
        todos_los_datos = []
        barra = st.progress(0)
        status = st.empty()
        total = len(lista_imagenes)
        
        for i, archivo in enumerate(lista_imagenes):
            nombre = archivo.name if hasattr(archivo, 'name') else "Cámara"
            status.info(f"Analizando {i+1}/{total}...")
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
                        
                        # Corrección lote A->P
                        def corregir_lote(row):
                            l = str(row['Lote'])
                            if row['CATEGORIA'] == 'TAPON' and l.startswith('A'): return 'P' + l[1:]
                            return l
                        df['Lote'] = df.apply(corregir_lote, axis=1)
                        
                        todos_los_datos.append(df)
                    else:
                        st.warning(f"⚠️ {nombre}: Formato ilegible.")
                else:
                    st.error(f"❌ {nombre}: Sin datos.")
            except Exception as e:
                st.error(f"❌ Error: {e}")
            barra.progress((i + 1) / total)
        
        status.empty()
        barra.empty()
        
        if todos_los_datos:
            df_final = pd.concat(todos_los_datos)
            
            # Totales
            resumen_global = df_final.groupby(["CATEGORIA"])["Cantidad_Num"].sum().reset_index()
            resumen_global.columns = ["Material", "Total"]
            resumen_global['Total'] = resumen_global['Total'].apply(lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            
            resumen_lotes = df_final.groupby(["CATEGORIA", "Lote"])["Cantidad_Num"].sum().reset_index()
            resumen_lotes.columns = ["Categoría", "Lote", "Total"]
            resumen_lotes['Total'] = resumen_lotes['Total'].apply(lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            
            st.success("✅ ¡Cálculo Corregido!")
            st.subheader("📦 TOTALES REALES")
            st.dataframe(resumen_global, use_container_width=True)
            
            st.subheader("📋 DESGLOSE")
            st.dataframe(resumen_lotes, use_container_width=True)
            
            csv = resumen_lotes.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Descargar CSV", csv, "produccion_real.csv", "text/csv", use_container_width=True)
