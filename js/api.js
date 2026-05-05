const API = "";

async function api(url, options = {}) {
    const res = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Error" }));
        throw new Error(err.detail || "Error en la solicitud");
    }
    return res.json();
}

function get(url) { return api(url); }
function post(url, data) { return api(url, { method: "POST", body: JSON.stringify(data) }); }
function put(url, data) { return api(url, { method: "PUT", body: JSON.stringify(data) }); }
function del(url) { return api(url, { method: "DELETE" }); }

function fmt(n) { return "$" + Number(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function fechaNow() { const d = new Date(); return d.toLocaleDateString("es-AR") + " " + d.toLocaleTimeString("es-AR"); }
function fechaDate() { const d = new Date(); return d.toLocaleDateString("es-AR"); }
function mostrar(msg) { alert(msg); }
function confirmar(msg) { return confirm(msg); }
function descargarPDF(base64, nombre) {
    const link = document.createElement("a");
    link.href = "data:application/pdf;base64," + base64;
    link.download = nombre;
    link.click();
}
function ir(ruta) { window.location.href = ruta; }
