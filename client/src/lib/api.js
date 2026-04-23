"use client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
const TOKEN = process.env.NEXT_PUBLIC_API_TOKEN || "admin";

const getHeaders = () => ({
  "Content-Type": "application/json",
  "x-token": TOKEN,
});

export const api = {
  agents: {
    list: async () => {
      const res = await fetch(`${API_URL}/agents/`, { headers: getHeaders() });
      if (!res.ok) throw new Error("Failed to fetch agents");
      return res.json();
    },
    get: async (id) => {
      const res = await fetch(`${API_URL}/agents/${id}`, { headers: getHeaders() });
      if (!res.ok) throw new Error("Failed to fetch agent");
      return res.json();
    },
    create: async (data) => {
      const res = await fetch(`${API_URL}/agents/`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error("Failed to create agent");
      return res.json();
    },
    update: async (id, data) => {
      const res = await fetch(`${API_URL}/agents/${id}`, {
        method: "PUT",
        headers: getHeaders(),
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error("Failed to update agent");
      return res.json();
    },
    delete: async (id) => {
      const res = await fetch(`${API_URL}/agents/${id}`, {
        method: "DELETE",
        headers: getHeaders(),
      });
      if (!res.ok) throw new Error("Failed to delete agent");
      return res.json();
    }
  },
  tools: {
    create: async (data) => {
      const res = await fetch(`${API_URL}/tools/`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error("Failed to create tool");
      return res.json();
    },
    update: async (id, data) => {
      const res = await fetch(`${API_URL}/tools/${id}`, {
        method: "PUT",
        headers: getHeaders(),
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error("Failed to update tool");
      return res.json();
    },
    delete: async (id) => {
      const res = await fetch(`${API_URL}/tools/${id}`, {
        method: "DELETE",
        headers: getHeaders(),
      });
      if (!res.ok) throw new Error("Failed to delete tool");
      return res.json();
    }
  },
  calls: {
    list: async (agent_id = null) => {
      let url = `${API_URL}/calls/`;
      if (agent_id) {
        url += `?agent_id=${agent_id}`;
      }
      const res = await fetch(url, { headers: getHeaders() });
      if (!res.ok) throw new Error("Failed to fetch calls");
      return res.json();
    },
    get: async (id) => {
      const res = await fetch(`${API_URL}/calls/${id}`, { headers: getHeaders() });
      if (!res.ok) throw new Error("Failed to fetch call detail");
      return res.json();
    }
  },
  chat: {
    send: async (agentId, messages, previousResponseId = null) => {
      const payload = { messages };
      if (previousResponseId) {
        payload.previous_response_id = previousResponseId;
      }
      const res = await fetch(`${API_URL}/chat/${agentId}`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error("Failed to send message");
      return res.json();
    }
  }
};
