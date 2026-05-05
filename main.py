import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
import sqlite3
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
import io
import base64

load_dotenv()

app = FastAPI(title="VapeHouse API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Conexión SQLite local para migrar datos existentes
DB_NAME = 'vapehouse_datos.db'

# ==========================================
# MODELOS
# ==========================================

class LoginRequest(BaseModel):
    usuario: str
    clave: str

class Producto(BaseModel):
    id: Optional[int] = None
    categoria: str
    nombre: str
    costo: float
    venta: float
    cantidad: int

class Venta(BaseModel):
    fecha: str
    producto: str
    unidades: int
    ganancia: float

class Gasto(BaseModel):
    concepto: str
    monto: float

class ClienteFactura(BaseModel):
    nombre: str
    apellido: str
    cedula: str
    telefono: str
    correo: str
    producto: str
    cantidad: int
    precio_unit: float
    total_venta: float
    id_venta: int

# ==========================================
# AUTH
# ==========================================

@app.post("/api/login")
def login(req: LoginRequest):
    if req.usuario == "admin" and req.clave == "admin":
        return {"status": "ok", "token": "vapehouse_session"}
    # Si falla, nos dice qué recibió exactamente:
    raise HTTPException(status_code=401, detail=f"Recibido: usuario='{req.usuario}', clave='{req.clave}'")
    
# ==========================================
# PRODUCTOS
# ==========================================

@app.get("/api/productos")
def get_productos(filtro: Optional[str] = ""):
    if filtro:
        response = supabase.table("productos").select("*").ilike("nombre", f"%{filtro}%").execute()
        if not response.data:
            response = supabase.table("productos").select("*").ilike("categoria", f"%{filtro}%").execute()
    else:
        response = supabase.table("productos").select("*").order("id").execute()
    return response.data

@app.post("/api/productos")
def crear_producto(p: Producto):
    response = supabase.table("productos").insert({
        "categoria": p.categoria,
        "nombre": p.nombre,
        "costo": p.costo,
        "venta": p.venta,
        "cantidad": p.cantidad
    }).execute()
    registrar_historial(p.nombre, "INGRESO", p.cantidad, "Nuevo producto registrado")
    return response.data

@app.put("/api/productos/{id}")
def actualizar_producto(id: int, p: Producto):
    response = supabase.table("productos").update({
        "categoria": p.categoria,
        "nombre": p.nombre,
        "costo": p.costo,
        "venta": p.venta,
        "cantidad": p.cantidad
    }).eq("id", id).execute()
    return response.data

@app.post("/api/productos/sumar_stock")
def sumar_stock(nombre: str, cantidad: int, categoria: str, costo: float, venta: float):
    response = supabase.table("productos").update({
        "cantidad": supabase.rpc("increment_cantidad") if False else None
    }).execute()
    actual = supabase.table("productos").select("cantidad").eq("nombre", nombre).execute()
    if actual.data:
        nuevo_stock = actual.data[0]["cantidad"] + cantidad
        supabase.table("productos").update({
            "cantidad": nuevo_stock,
            "costo": costo,
            "venta": venta,
            "categoria": categoria
        }).eq("nombre", nombre).execute()
        registrar_historial(nombre, "ENTRADA", cantidad, "Reposición de stock")
    return {"status": "ok"}

@app.delete("/api/productos/{id}")
def eliminar_producto(id: int):
    prod = supabase.table("productos").select("nombre").eq("id", id).execute()
    if prod.data:
        registrar_historial(prod.data[0]["nombre"], "ELIMINACION", 0, "Producto eliminado del sistema")
    response = supabase.table("productos").delete().eq("id", id).execute()
    return response.data

# ==========================================
# VENTAS
# ==========================================

@app.get("/api/ventas")
def get_ventas(periodo: Optional[str] = ""):
    hoy = datetime.now()
    if periodo == "HOY":
        fecha_like = f"{hoy.strftime('%#d/%#m/%Y')}%"
        response = supabase.table("ventas").select("*").ilike("fecha", fecha_like).execute()
    elif periodo == "SEMANAL":
        h_s = (hoy - __import__('datetime').timedelta(days=7)).strftime('%Y%m%d')
        response = supabase.table("ventas").select("*").execute()
        response = type(response)(data=[r for r in response.data if fecha_cmp_gte(r.get("fecha", ""), h_s)])
    elif periodo == "MES ACTUAL":
        fecha_like = f"%/{hoy.strftime('%#m/%Y')}%"
        response = supabase.table("ventas").select("*").ilike("fecha", fecha_like).execute()
    elif periodo == "AÑO ACTUAL":
        fecha_like = f"%/%/{hoy.strftime('%Y')}%"
        response = supabase.table("ventas").select("*").ilike("fecha", fecha_like).execute()
    else:
        supabase.table("ventas").delete().gt("id_venta", 0).execute()
    return {"status": "ok"}

@app.post("/api/ventas")
def crear_venta(v: Venta):
    response = supabase.table("ventas").insert({
        "fecha": v.fecha,
        "producto": v.producto,
        "unidades": v.unidades,
        "ganancia": v.ganancia
    }).execute()
    id_venta = response.data[0]["id_venta"] if response.data else 0
    registrar_historial(v.producto, "VENTA", v.unidades, "Venta realizada")
    return {"id_venta": id_venta, "status": "ok"}

@app.delete("/api/ventas")
def eliminar_ventas(periodo: Optional[str] = ""):
    if periodo == "HOY":
        fecha_like = f"{datetime.now().strftime('%#d/%#m/%Y')}%"
        supabase.table("ventas").delete().ilike("fecha", fecha_like).execute()
    else:
        supabase.table("ventas").delete().execute()
    return {"status": "ok"}

def fecha_cmp_gte(fecha_str, h_s):
    if not fecha_str:
        return False
    parts = fecha_str.split("/")
    if len(parts) >= 3:
        formatted = f"{parts[2]}{int(parts[1]):02d}{int(parts[0]):02d}"
        return formatted >= h_s
    return False

# ==========================================
# HISTORIAL
# ==========================================

def registrar_historial(producto, tipo, cantidad, detalle):
    fecha = datetime.now().strftime("%#d/%#m/%Y %H:%M:%S")
    supabase.table("historial").insert({
        "fecha": fecha,
        "producto": producto,
        "tipo_mov": tipo,
        "cantidad_mov": cantidad,
        "detalle": detalle
    }).execute()

@app.get("/api/historial")
def get_historial():
    response = supabase.table("historial").select("*").order("id_mov", desc=True).execute()
    return response.data

@app.delete("/api/historial")
def limpiar_historial():
    supabase.table("historial").delete().gt("id_mov", 0).execute()
    return {"status": "ok"}

# ==========================================
# GASTOS
# ==========================================

@app.get("/api/gastos")
def get_gastos(periodo: Optional[str] = "HOY"):
    hoy = datetime.now()
    if periodo == "HOY":
        fecha_val = hoy.strftime('%#d/%#m/%Y')
        response = supabase.table("gastos").select("*").eq("fecha", fecha_val).execute()
    elif periodo == "SEMANAL":
        h_s = (hoy - __import__('datetime').timedelta(days=7)).strftime('%Y%m%d')
        response = supabase.table("gastos").select("*").execute()
        response = type(response)(data=[r for r in response.data if fecha_cmp_gte(r.get("fecha", ""), h_s)])
    elif periodo == "MENSUAL":
        fecha_like = f"%/{hoy.strftime('%#m/%Y')}%"
        response = supabase.table("gastos").select("*").ilike("fecha", fecha_like).execute()
    elif periodo == "ANUAL":
        fecha_like = f"%/%/{hoy.strftime('%Y')}%"
        response = supabase.table("gastos").select("*").ilike("fecha", fecha_like).execute()
    else:
        supabase.table("gastos").delete().gt("id_gasto", 0).execute()
    return {"status": "ok"}

@app.post("/api/gastos")
def crear_gasto(g: Gasto):
    fecha = datetime.now().strftime("%d/%m/%Y")
    response = supabase.table("gastos").insert({
        "fecha": fecha,
        "concepto": g.concepto,
        "monto": g.monto
    }).execute()
    return response.data

@app.delete("/api/gastos")
def eliminar_gastos(periodo: Optional[str] = "HOY"):
    hoy = datetime.now()
    if periodo == "HOY":
        fecha_val = hoy.strftime('%#d/%#m/%Y')
        supabase.table("gastos").delete().eq("fecha", fecha_val).execute()
    elif periodo == "SEMANAL":
        h_s = (hoy - __import__('datetime').timedelta(days=7)).strftime('%Y%m%d')
        all_gastos = supabase.table("gastos").select("*").execute()
        ids = [r["id_gasto"] for r in all_gastos.data if fecha_cmp_gte(r.get("fecha", ""), h_s)]
        if ids:
            supabase.table("gastos").delete().in_("id_gasto", ids).execute()
    elif periodo == "MENSUAL":
        fecha_like = f"%/{hoy.strftime('%#m/%Y')}%"
        all_gastos = supabase.table("gastos").select("*").ilike("fecha", fecha_like).execute()
        ids = [r["id_gasto"] for r in all_gastos.data]
        if ids:
            supabase.table("gastos").delete().in_("id_gasto", ids).execute()
    elif periodo == "ANUAL":
        fecha_like = f"%/%/{hoy.strftime('%Y')}%"
        all_gastos = supabase.table("gastos").select("*").ilike("fecha", fecha_like).execute()
        ids = [r["id_gasto"] for r in all_gastos.data]
        if ids:
            supabase.table("gastos").delete().in_("id_gasto", ids).execute()
    else:
        supabase.table("gastos").delete().execute()
    return {"status": "ok"}

# ==========================================
# RESUMEN FINANCIERO
# ==========================================

@app.get("/api/resumen")
def get_resumen(periodo: Optional[str] = "HOY"):
    hoy = datetime.now()
    if periodo == "HOY":
        fecha_like = f"{hoy.strftime('%#d/%#m/%Y')}%"
        ventas = supabase.table("ventas").select("ganancia").ilike("fecha", fecha_like).execute()
    elif periodo == "SEMANAL":
        h_s = (hoy - __import__('datetime').timedelta(days=7)).strftime('%Y%m%d')
        ventas = supabase.table("ventas").select("*").execute()
        ventas = type(ventas)(data=[r for r in ventas.data if fecha_cmp_gte(r.get("fecha", ""), h_s)])
    elif periodo == "MENSUAL":
        fecha_like = f"%/{hoy.strftime('%#m/%Y')}%"
        ventas = supabase.table("ventas").select("ganancia").ilike("fecha", fecha_like).execute()
    elif periodo == "ANUAL":
        fecha_like = f"%/%/{hoy.strftime('%Y')}%"
        ventas = supabase.table("ventas").select("ganancia").ilike("fecha", fecha_like).execute()
    else:
        ventas = supabase.table("ventas").select("ganancia").execute()

    total_ventas = sum(r.get("ganancia", 0) for r in ventas.data or [])

    if periodo == "HOY":
        fecha_val = hoy.strftime('%#d/%#m/%Y')
        gastos = supabase.table("gastos").select("monto").eq("fecha", fecha_val).execute()
    elif periodo == "SEMANAL":
        h_s = (hoy - __import__('datetime').timedelta(days=7)).strftime('%Y%m%d')
        gastos = supabase.table("gastos").select("*").execute()
        gastos = type(gastos)(data=[r for r in gastos.data if fecha_cmp_gte(r.get("fecha", ""), h_s)])
    elif periodo == "MENSUAL":
        fecha_like = f"%/{hoy.strftime('%#m/%Y')}%"
        gastos = supabase.table("gastos").select("monto").ilike("fecha", fecha_like).execute()
    elif periodo == "ANUAL":
        fecha_like = f"%/%/{hoy.strftime('%Y')}%"
        gastos = supabase.table("gastos").select("monto").ilike("fecha", fecha_like).execute()
    else:
        gastos = supabase.table("gastos").select("monto").execute()

    total_gastos = sum(r.get("monto", 0) for r in gastos.data or [])

    return {
        "ganancia_bruta": total_ventas,
        "gastos": total_gastos,
        "utilidad": total_ventas - total_gastos
    }

# ==========================================
# ANÁLISIS BI
# ==========================================

@app.get("/api/analisis/rendimiento")
def get_rendimiento():
    hoy = datetime.now()
    resultados = {}
    periodos = {
        "HOY": f"{hoy.strftime('%#d/%#m/%Y')}%",
        "ESTE MES": f"%/{hoy.strftime('%#m/%Y')}%",
        "ESTE AÑO": f"%/%/{hoy.strftime('%Y')}%",
        "TOTAL": None
    }
    for titulo, fecha_like in periodos.items():
        if fecha_like:
            resp = supabase.table("ventas").select("ganancia").ilike("fecha", fecha_like).execute()
        else:
            resp = supabase.table("ventas").select("ganancia").execute()
        gan = sum(r.get("ganancia", 0) for r in resp.data or [])
        cnt = len(resp.data or [])
        resultados[titulo] = {"ganancia": gan, "ventas": cnt}

    detalle = []
    for i in range(29, -1, -1):
        dia = (hoy - __import__('datetime').timedelta(days=i)).strftime('%#d/%#m/%Y')
        resp = supabase.table("ventas").select("*").ilike("fecha", f"{dia}%").execute()
        cnt_v = len(resp.data or [])
        unds = sum(r.get("unidades", 0) for r in resp.data or [])
        gan = sum(r.get("ganancia", 0) for r in resp.data or [])
        ticket = (gan / cnt_v) if cnt_v > 0 else 0
        detalle.append({
            "fecha": dia,
            "ventas": cnt_v,
            "unidades": unds,
            "ganancia": gan,
            "ticket_promedio": ticket
        })

    return {"periodos": resultados, "detalle": detalle}

@app.get("/api/analisis/productos_estrella")
def get_productos_estrella(periodo: Optional[str] = "ESTE MES"):
    hoy = datetime.now()
    ventas_resp = supabase.table("ventas").select("*").execute()
    ventas = ventas_resp.data or []

    if periodo == "HOY":
        fecha_like = f"{hoy.strftime('%#d/%#m/%Y')}%"
        ventas = [v for v in ventas if v.get("fecha", "").startswith(fecha_like[:-1].split("%")[0])]
    elif periodo == "ESTE MES":
        fecha_like = f"%/{hoy.strftime('%#m/%Y')}%"
        ventas = [v for v in ventas if __import__('fnmatch').fnmatch(v.get("fecha", ""), fecha_like)]
    elif periodo == "ESTE AÑO":
        fecha_like = f"%/%/{hoy.strftime('%Y')}%"
        ventas = [v for v in ventas if __import__('fnmatch').fnmatch(v.get("fecha", ""), fecha_like)]

    from collections import defaultdict
    stats = defaultdict(lambda: {"unidades": 0, "ganancia": 0, "transacciones": 0})
    for v in ventas:
        prod = v.get("producto", "Desconocido")
        stats[prod]["unidades"] += v.get("unidades", 0)
        stats[prod]["ganancia"] += v.get("ganancia", 0)
        stats[prod]["transacciones"] += 1

    productos_resp = supabase.table("productos").select("*").execute()
    productos_map = {p["nombre"].lower(): p for p in productos_resp.data or []}

    ranking = []
    for prod, data in sorted(stats.items(), key=lambda x: x[1]["unidades"], reverse=True):
        p_info = productos_map.get(prod.lower(), {})
        costo = p_info.get("costo", 0)
        venta = p_info.get("venta", 0)
        margen = ((venta - costo) / venta * 100) if venta and venta > 0 else 0
        ranking.append({
            "producto": prod,
            "unidades": data["unidades"],
            "ganancia_total": data["ganancia"],
            "transacciones": data["transacciones"],
            "margen": round(margen, 1)
        })

    return ranking

@app.get("/api/analisis/recomendaciones")
def get_recomendaciones():
    hoy = datetime.now()
    productos = supabase.table("productos").select("*").execute()
    ventas = supabase.table("ventas").select("*").execute()
    hace_30 = (hoy - __import__('datetime').timedelta(days=30)).strftime('%Y%m%d')

    alertas = []
    oportunidades = []
    analisis = []

    for p in productos.data or []:
        nombre = p["nombre"]
        stock = p.get("cantidad", 0)
        costo = p.get("costo", 0)
        precio_venta = p.get("venta", 0)
        margen = ((precio_venta - costo) / precio_venta * 100) if precio_venta > 0 else 0

        ventas_30 = sum(v.get("unidades", 0) for v in ventas.data or []
                       if v.get("producto", "").lower() == nombre.lower()
                       and fecha_cmp_gte(v.get("fecha", ""), hace_30))

        rotacion = ventas_30 / 30 if ventas_30 > 0 else 0
        dias_stock = int(stock / rotacion) if rotacion > 0 else 999

        if stock <= 3 and ventas_30 > 0:
            estado = "CRITICO"
            accion = "REPOSICIÓN URGENTE — alta demanda"
            alertas.append(f"⚠ {nombre}: solo {stock} uds, {ventas_30} vendidas en 30d → REPONER")
        elif stock <= 3 and ventas_30 == 0:
            estado = "SIN_MOVIMIENTO"
            accion = "Evaluar descontinuar o promocionar"
        elif margen >= 40 and ventas_30 >= 5:
            estado = "ESTRELLA"
            accion = f"INVERTIR MÁS — margen {margen:.0f}%"
            oportunidades.append(f"💰 {nombre}: margen {margen:.0f}%, {ventas_30} uds/30d → Ampliar stock")
        elif margen >= 40 and ventas_30 < 5:
            estado = "ALTO_MARGEN"
            accion = "Promover — buen margen, baja rotación"
            oportunidades.append(f"📢 {nombre}: margen {margen:.0f}% — necesita visibilidad")
        elif dias_stock < 7 and ventas_30 > 0:
            estado = "POR_AGOTAR"
            accion = f"Reponer — ~{dias_stock}d de stock"
            alertas.append(f"🔴 {nombre}: stock para ~{dias_stock} días → PLANIFICAR COMPRA")
        elif ventas_30 == 0 and stock > 10:
            estado = "ESTANCADO"
            accion = "Sin ventas 30d — considerar descuento"
        else:
            estado = "NORMAL"
            accion = "Mantener operación actual"

        dias_txt = f"~{dias_stock}d" if dias_stock < 999 else "∞"
        analisis.append({
            "producto": nombre,
            "stock": stock,
            "margen": round(margen, 1),
            "ventas_30d": ventas_30,
            "dias_stock": dias_txt,
            "estado": estado,
            "accion_sugerida": accion
        })

    return {
        "alertas": alertas if alertas else ["✅ Sin alertas críticas."],
        "oportunidades": oportunidades if oportunidades else ["ℹ️ Sin oportunidades destacadas."],
        "analisis": analisis
    }

# ==========================================
# PDF
# ==========================================

@app.get("/api/pdf/ventas")
def generar_pdf_ventas(periodo: Optional[str] = "GENERAL"):
    ventas = supabase.table("ventas").select("*").execute()
    filas = ventas.data or []

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elementos = []
    estilos = getSampleStyleSheet()

    elementos.append(Paragraph(f"VAPEHOUSE — REPORTE VENTAS ({periodo})", estilos['Title']))
    elementos.append(Paragraph(f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}", estilos['Normal']))
    elementos.append(Spacer(1, 12))

    datos = [["ID", "FECHA", "PRODUCTO", "UNIDADES", "GANANCIA"]]
    total = 0
    for v in filas:
        datos.append([v["id_venta"], v["fecha"], v["producto"], v["unidades"], f"${v['ganancia']:,.2f}"])
        total += v.get("ganancia", 0)
    datos.append(["", "", "", "TOTAL:", f"${total:,.2f}"])

    t = Table(datos)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A5F')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#D1FAE5')),
    ]))
    elementos.append(t)
    doc.build(elementos)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode()

@app.post("/api/pdf/factura")
def generar_factura_cliente(f: ClienteFactura):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=40, bottomMargin=40, leftMargin=50, rightMargin=50)
    elementos = []
    estilos = getSampleStyleSheet()

    elementos.append(Paragraph("VAPEHOUSE", estilos['Title']))
    elementos.append(Paragraph("FACTURA DE VENTA", estilos['Heading2']))
    elementos.append(Paragraph(f"No. Factura: {f.id_venta:05d} | Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}", estilos['Normal']))
    elementos.append(Spacer(1, 16))

    elementos.append(Paragraph("DATOS DEL CLIENTE", estilos['Heading3']))
    t_cli = Table([
        ["Nombre:", f"{f.nombre} {f.apellido}"],
        ["Cédula:", f.cedula],
        ["Teléfono:", f.telefono],
        ["Correo:", f.correo],
    ], colWidths=[120, 350])
    t_cli.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
    ]))
    elementos.append(t_cli)
    elementos.append(Spacer(1, 16))

    elementos.append(Paragraph("DETALLE DE LA VENTA", estilos['Heading3']))
    t_prod = Table([
        ["PRODUCTO", "CANT.", "PRECIO", "TOTAL"],
        [f.producto, str(f.cantidad), f"${f.precio_unit:,.2f}", f"${f.total_venta:,.2f}"]
    ], colWidths=[200, 70, 110, 110])
    t_prod.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A5F')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
    ]))
    elementos.append(t_prod)
    elementos.append(Spacer(1, 12))

    t_total = Table([["TOTAL A PAGAR:", f"${f.total_venta:,.2f}"]], colWidths=[300, 190])
    t_total.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 14),
        ('TEXTCOLOR', (1, 0), (1, 0), colors.HexColor('#10B981')),
    ]))
    elementos.append(t_total)

    doc.build(elementos)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode()

# ==========================================
# MIGRACIÓN DESDE SQLITE
# ==========================================

@app.post("/api/migrar")
def migrar_desde_sqlite():
    if not os.path.exists(DB_NAME):
        return {"status": "error", "message": "No se encontró la base de datos local"}

    local_conn = sqlite3.connect(DB_NAME)
    cursor = local_conn.cursor()

    cursor.execute("SELECT * FROM productos")
    for row in cursor.fetchall():
        supabase.table("productos").insert({
            "categoria": row[1], "nombre": row[2], "costo": row[3],
            "venta": row[4], "cantidad": row[5]
        }).execute()

    cursor.execute("SELECT * FROM ventas")
    for row in cursor.fetchall():
        supabase.table("ventas").insert({
            "fecha": row[1], "producto": row[2], "unidades": row[3], "ganancia": row[4]
        }).execute()

    cursor.execute("SELECT * FROM historial")
    for row in cursor.fetchall():
        supabase.table("historial").insert({
            "fecha": row[1], "producto": row[2], "tipo_mov": row[3],
            "cantidad_mov": row[4], "detalle": row[5]
        }).execute()

    cursor.execute("SELECT * FROM gastos")
    for row in cursor.fetchall():
        supabase.table("gastos").insert({
            "fecha": row[1], "concepto": row[2], "monto": row[3]
        }).execute()

    local_conn.close()
    return {"status": "ok", "message": "Datos migrados correctamente"}

# ==========================================
# SERVE STATIC
# ==========================================

app.mount("/", StaticFiles(directory=".", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
