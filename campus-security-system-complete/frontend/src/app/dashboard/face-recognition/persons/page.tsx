'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { LoadingSpinner } from '@/components/ui/loading-spinner'
import { Users, Search, RefreshCw, User, Trash2 } from 'lucide-react'
import Link from 'next/link'

interface Person {
  id: string
  person_id: string
  person_name: string
  department: string | null
  employee_id: string | null
  is_active: boolean
  created_at: string | null
}

export default function PersonsPage() {
  const [persons, setPersons] = useState<Person[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')

  const fetchPersons = async () => {
    try {
      setLoading(true)
      const res = await api.get('/face/persons')
      setPersons(res.data.items || [])
    } catch (err: any) {
      setError(err.detail || 'Failed to load enrolled persons')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchPersons() }, [])

  const handleDelete = async (personId: string) => {
    if (!confirm('Are you sure you want to remove this person?')) return
    try {
      await api.delete(`/face/persons/${personId}`)
      fetchPersons()
    } catch (err: any) {
      setError(err.detail || 'Failed to delete person')
    }
  }

  const filtered = persons.filter(p =>
    (p.person_id || '').toLowerCase().includes(search.toLowerCase()) ||
    (p.person_name || '').toLowerCase().includes(search.toLowerCase())
  )

  if (loading) {
    return <div className="flex items-center justify-center h-64"><LoadingSpinner size="lg" /></div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Enrolled Persons</h1>
          <p className="text-gray-500 dark:text-gray-400">{persons.length} persons enrolled in the system</p>
        </div>
        <div className="flex gap-2">
          <Link href="/dashboard/face-recognition/enroll">
            <Button className="bg-blue-600 hover:bg-blue-700 text-white">
              <Users className="h-4 w-4 mr-2" /> Enroll New
            </Button>
          </Link>
          <Button variant="outline" onClick={fetchPersons}>
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
        <input type="text" placeholder="Search persons..."
          className="w-full pl-10 pr-4 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
          value={search} onChange={e => setSearch(e.target.value)} />
      </div>

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map(person => (
          <Card key={person.person_id} className="hover:shadow-lg transition-shadow">
            <CardContent className="p-4">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="h-12 w-12 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center">
                    <User className="h-6 w-6 text-blue-600 dark:text-blue-400" />
                  </div>
                  <div>
                    <h3 className="font-medium text-gray-900 dark:text-white">{person.person_name}</h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400">{person.person_id}</p>
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={() => handleDelete(person.person_id)} className="text-red-500 hover:text-red-700">
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
                {person.department && (
                  <div>
                    <span className="text-gray-500 dark:text-gray-400">Dept:</span>{' '}
                    <span className="text-gray-900 dark:text-white">{person.department}</span>
                  </div>
                )}
                {person.employee_id && (
                  <div>
                    <span className="text-gray-500 dark:text-gray-400">Employee ID:</span>{' '}
                    <span className="text-gray-900 dark:text-white">{person.employee_id}</span>
                  </div>
                )}
                <div>
                  <Badge variant={person.is_active ? 'success' : 'secondary'}>{person.is_active ? 'Active' : 'Inactive'}</Badge>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {filtered.length === 0 && !loading && (
        <div className="text-center py-12">
          <Users className="h-12 w-12 mx-auto text-gray-400 mb-4" />
          <h3 className="text-lg font-medium text-gray-900 dark:text-white">No persons enrolled</h3>
          <p className="text-gray-500 dark:text-gray-400 mb-4">Get started by enrolling a new person.</p>
          <Link href="/dashboard/face-recognition/enroll">
            <Button className="bg-blue-600 hover:bg-blue-700 text-white">Enroll Person</Button>
          </Link>
        </div>
      )}
    </div>
  )
}
