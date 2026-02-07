import api from './api'

export interface LoginCredentials {
    username: string
    password: string
    tenant_slug: string
}

export interface RegisterData {
    username: string
    email: string
    password: string
    tenant_id: number
    role?: string
}

export const authService = {
    login: async (credentials: LoginCredentials) => {
        const response = await api.post('/auth/login', credentials)
        return response.data
    },

    register: async (data: RegisterData) => {
        const response = await api.post('/auth/register', data)
        return response.data
    },

    getCurrentUser: async () => {
        const response = await api.get('/auth/me')
        return response.data
    },
}
