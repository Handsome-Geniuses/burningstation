
const baseUrl = "/flask/system/"

export const flask = {
    get: (path: string, options?: RequestInit) => fetch(baseUrl + path, { ...options, method: "GET" }),
    post: (path: string, options?: RequestInit) => 
        fetch(baseUrl + path, { ...options, 
            method: "POST",
            headers: { ...(options?.body ? { 'Content-Type': 'application/json' } : {}), ...options?.headers }
         }),
    put: (path: string, options?: RequestInit) => fetch(baseUrl + path, { ...options, method: "PUT" }),
    delete: (path: string, options?: RequestInit) => fetch(baseUrl + path, { ...options, method: "DELETE" }),
    patch: (path: string, options?: RequestInit) => fetch(baseUrl + path, { ...options, method: "PATCH" }),
}