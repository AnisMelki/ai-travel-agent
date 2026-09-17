const ENDPOINT = "/flight/search";
const STORAGE_KEY = "conversation_id";

const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("chat-form");
const inputEl = document.getElementById("message");
const sendEl = document.getElementById("send");
const resetEl = document.getElementById("reset");
const badgeEl = document.getElementById("conversation-badge");
const progressEl = document.getElementById("progress");

// Elapsed seconds after which each label takes over.
const PROGRESS_STAGES = [
    [0, "Analyse de votre demande"],
    [3, "Résolution des aéroports"],
    [7, "Recherche des vols disponibles"],
    [18, "Comparaison des prix et des avis compagnies"],
    [30, "Sélection des meilleures options"],
];

let busy = false;

function conversationId() {
    let id = localStorage.getItem(STORAGE_KEY);
    if (!id) {
        // Generated client-side so the thread survives a failed first turn,
        // where the server never gets to echo back its own id.
        id = crypto.randomUUID();
        localStorage.setItem(STORAGE_KEY, id);
        renderBadge();
    }
    return id;
}

function setConversationId(id) {
    if (!id) {
        return;
    }
    localStorage.setItem(STORAGE_KEY, id);
    renderBadge();
}

function renderBadge() {
    const id = localStorage.getItem(STORAGE_KEY);
    badgeEl.hidden = !id;
    badgeEl.textContent = id ? `conversation ${id.slice(0, 8)}` : "";
}

function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addBubble(text, kind) {
    const el = document.createElement("div");
    el.className = `msg ${kind}`;
    el.textContent = text;
    messagesEl.appendChild(el);
    scrollToBottom();
    return el;
}

function startProgress() {
    progressEl.hidden = false;

    const bubble = document.createElement("div");
    bubble.className = "msg agent pending";

    const dots = document.createElement("span");
    dots.className = "dots";
    dots.append(
        document.createElement("span"),
        document.createElement("span"),
        document.createElement("span"),
    );

    const label = document.createElement("span");
    label.className = "pending-label";
    label.textContent = `${PROGRESS_STAGES[0][1]}…`;

    const elapsed = document.createElement("span");
    elapsed.className = "pending-elapsed";
    elapsed.textContent = "0s";

    bubble.append(dots, label, elapsed);
    messagesEl.appendChild(bubble);
    scrollToBottom();

    const startedAt = Date.now();
    const timer = setInterval(() => {
        const seconds = Math.floor((Date.now() - startedAt) / 1000);
        elapsed.textContent = `${seconds}s`;
        const stage = PROGRESS_STAGES.filter(([at]) => at <= seconds).pop();
        label.textContent = `${stage[1]}…`;
    }, 1000);

    return () => {
        clearInterval(timer);
        bubble.remove();
        progressEl.hidden = true;
    };
}

function addOptions(bubble, options) {
    if (!Array.isArray(options) || options.length === 0) {
        return;
    }
    const wrapper = document.createElement("div");
    wrapper.className = "options";
    for (const option of options) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "option-btn";
        button.textContent = option.label ?? option.value;
        button.addEventListener("click", () => {
            wrapper
                .querySelectorAll("button")
                .forEach((btn) => (btn.disabled = true));
            sendMessage(String(option.value));
        });
        wrapper.appendChild(button);
    }
    bubble.appendChild(wrapper);
    scrollToBottom();
}

function formatTime(value) {
    if (!value) {
        return "—";
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime())
        ? value
        : parsed.toLocaleString(undefined, {
              day: "2-digit",
              month: "short",
              hour: "2-digit",
              minute: "2-digit",
          });
}

function formatDuration(minutes) {
    if (typeof minutes !== "number") {
        return "—";
    }
    return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}`;
}

function formatPrice(result) {
    return result.price == null
        ? "—"
        : `${result.price} ${result.currency ?? ""}`.trim();
}

function cell(text, className) {
    const td = document.createElement("td");
    td.textContent = text;
    if (className) {
        td.className = className;
    }
    return td;
}

function buildDetailRow(legs, layovers, columns) {
    const row = document.createElement("tr");
    row.className = "flight-detail";
    row.hidden = true;

    const td = document.createElement("td");
    td.colSpan = columns;

    for (const leg of legs) {
        const line = document.createElement("div");
        line.className = "flight-leg";
        line.textContent = `${leg.airline} ${leg.flight_number} · ${leg.departure_airport?.id ?? "?"} ${formatTime(leg.departure_airport?.time)} → ${leg.arrival_airport?.id ?? "?"} ${formatTime(leg.arrival_airport?.time)} · ${formatDuration(leg.duration)}${leg.travel_class ? ` · ${leg.travel_class}` : ""}`;
        td.appendChild(line);
    }

    for (const layover of layovers) {
        const line = document.createElement("div");
        line.className = "flight-leg layover";
        line.textContent = `Escale à ${layover.name} (${layover.id}) · ${formatDuration(layover.duration)}`;
        td.appendChild(line);
    }

    row.appendChild(td);
    return row;
}

function addFlights(bubble, flights) {
    if (flights.length === 0) {
        const empty = document.createElement("div");
        empty.className = "flight-leg";
        empty.textContent = "Aucun vol n'a été retenu pour cette recherche.";
        bubble.appendChild(empty);
        return;
    }

    const headers = [
        "#",
        "Trajet",
        "Compagnie",
        "Départ",
        "Arrivée",
        "Durée",
        "Escales",
        "Prix",
    ];

    const scroller = document.createElement("div");
    scroller.className = "table-scroll";

    const table = document.createElement("table");
    table.className = "flights-table";

    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const header of headers) {
        const th = document.createElement("th");
        th.textContent = header;
        headRow.appendChild(th);
    }
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");

    for (const [index, result] of flights.entries()) {
        const legs = Array.isArray(result.flights) ? result.flights : [];
        const layovers = Array.isArray(result.layovers) ? result.layovers : [];
        const carriers = [...new Set(legs.map((leg) => leg.airline))].join(", ");
        const first = legs[0];
        const last = legs[legs.length - 1];

        const row = document.createElement("tr");
        row.className = "flight-row";
        row.tabIndex = 0;
        row.title = "Cliquer pour afficher le détail des segments";

        row.append(
            cell(String(index + 1), "rank"),
            cell(
                `${first?.departure_airport?.id ?? "?"} → ${last?.arrival_airport?.id ?? "?"}`,
                "route",
            ),
            cell(carriers || "—"),
            cell(formatTime(first?.departure_airport?.time)),
            cell(formatTime(last?.arrival_airport?.time)),
            cell(formatDuration(result.total_duration)),
            cell(layovers.length === 0 ? "Direct" : String(layovers.length)),
            cell(formatPrice(result), "price"),
        );

        const detail = buildDetailRow(legs, layovers, headers.length);
        const toggle = () => {
            detail.hidden = !detail.hidden;
            row.classList.toggle("expanded", !detail.hidden);
        };
        row.addEventListener("click", toggle);
        row.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                toggle();
            }
        });

        tbody.append(row, detail);
    }

    table.appendChild(tbody);
    scroller.appendChild(table);
    bubble.appendChild(scroller);
    scrollToBottom();
}

function renderResponse(payload) {
    if (payload && Array.isArray(payload.best_flights_selected)) {
        const bubble = addBubble(
            payload.reasoning || "Voici les vols sélectionnés.",
            "agent wide",
        );
        addFlights(bubble, payload.best_flights_selected);
        return;
    }

    switch (payload?.type) {
        case "clarification": {
            const bubble = addBubble(payload.message, "agent");
            addOptions(bubble, payload.options);
            return;
        }
        case "conversation":
            addBubble(payload.message, "agent");
            return;
        case "error":
            addBubble(payload.message, "error");
            return;
        default:
            addBubble("Réponse inattendue du serveur.", "error");
    }
}

async function sendMessage(message) {
    if (busy || !message.trim()) {
        return;
    }

    busy = true;
    sendEl.disabled = true;
    inputEl.disabled = true;

    addBubble(message, "user");
    const stopProgress = startProgress();

    try {
        const headers = {
            "Content-Type": "application/json",
            "X-Conversation-ID": conversationId(),
        };

        const response = await fetch(ENDPOINT, {
            method: "POST",
            headers,
            body: JSON.stringify({ message }),
        });

        setConversationId(response.headers.get("X-Conversation-ID"));

        let payload = null;
        try {
            payload = await response.json();
        } catch {
            payload = null;
        }

        stopProgress();

        if (!response.ok) {
            addBubble(
                payload?.message ?? `Erreur serveur (${response.status}).`,
                "error",
            );
            return;
        }

        renderResponse(payload);
    } catch {
        stopProgress();
        addBubble("Impossible de joindre le serveur.", "error");
    } finally {
        busy = false;
        sendEl.disabled = false;
        inputEl.disabled = false;
        inputEl.focus();
    }
}

formEl.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = inputEl.value;
    inputEl.value = "";
    sendMessage(message);
});

resetEl.addEventListener("click", () => {
    localStorage.removeItem(STORAGE_KEY);
    messagesEl.replaceChildren();
    renderBadge();
    addBubble("Nouvelle conversation démarrée. Où souhaitez-vous aller ?", "agent");
    inputEl.focus();
});

renderBadge();
addBubble("Bonjour ! Où souhaitez-vous aller ?", "agent");
