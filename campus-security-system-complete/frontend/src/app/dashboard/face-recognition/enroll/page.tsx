'use client'

import { useState, useRef } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { ArrowLeft, Upload, UserPlus, CheckCircle, AlertTriangle } from 'lucide-react'
import Link from 'next/link'

export default function EnrollPage() {
  const [form, setForm] = useState({ person_name: '', person_id: '', department: '', employee_id: '' })
  const [files, setFiles] = useState<File[]>([])
  const [preview, setPreview] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || [])
    if (selected.length > 0) {
      setFiles(selected)
      setPreview(URL.createObjectURL(selected[0]))
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (files.length === 0) { setError('Please select at least one image file'); return }
    if (!form.person_name) { setError('Person name is required'); return }

    setLoading(true)
    setError('')
    setResult(null)

    try {
      const { api } = await import('@/lib/api/client')
      const formData = new FormData()
      formData.append('person_name', form.person_name)
      files.forEach(f => formData.append('images', f))
      if (form.person_id) formData.append('person_id', form.person_id)
      if (form.department) formData.append('department', form.department)
      if (form.employee_id) formData.append('employee_id', form.employee_id)

      const res = await api.post('/face/enroll', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      setResult(res.data)
    } catch (err: any) {
      setError(err.detail || 'Enrollment failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link href="/dashboard/face-recognition/persons">
          <Button variant="outline" size="sm">
            <ArrowLeft className="h-4 w-4 mr-2" /> Back
          </Button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Enroll New Person</h1>
          <p className="text-gray-500 dark:text-gray-400">Add a person to the face recognition database</p>
        </div>
      </div>

      {result && (
        <div className="p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg">
          <div className="flex items-center gap-2 text-green-700 dark:text-green-300">
            <CheckCircle className="h-5 w-5" />
            <span className="font-medium">Enrollment successful!</span>
          </div>
          <p className="text-sm text-green-600 dark:text-green-400 mt-1">
            Person &quot;{form.person_name}&quot; has been enrolled with {result.faces_detected || 1} face(s) detected.
          </p>
        </div>
      )}

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
          <div className="flex items-center gap-2 text-red-700 dark:text-red-300">
            <AlertTriangle className="h-5 w-5" />
            <span>{error}</span>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <UserPlus className="h-5 w-5 text-blue-500" /> Person Details
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Person Name *</label>
                <input required value={form.person_name}
                  onChange={e => setForm(p => ({ ...p, person_name: e.target.value }))}
                  className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
                  placeholder="John Doe" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Person ID (optional)</label>
                <input value={form.person_id}
                  onChange={e => setForm(p => ({ ...p, person_id: e.target.value }))}
                  className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
                  placeholder="e.g., STU001 or EMP042" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Department</label>
                <input value={form.department}
                  onChange={e => setForm(p => ({ ...p, department: e.target.value }))}
                  className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
                  placeholder="Computer Science" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Employee ID</label>
                <input value={form.employee_id}
                  onChange={e => setForm(p => ({ ...p, employee_id: e.target.value }))}
                  className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
                  placeholder="EMP-042" />
              </div>
              <Button type="submit" disabled={loading} className="w-full bg-blue-600 hover:bg-blue-700 text-white">
                {loading ? 'Enrolling...' : 'Enroll Person'}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Upload className="h-5 w-5 text-blue-500" /> Face Image
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div
              className="border-2 border-dashed rounded-lg p-8 text-center cursor-pointer hover:border-blue-400 transition-colors"
              onClick={() => fileRef.current?.click()}>
              {preview ? (
                <img src={preview} alt="Preview" className="max-h-64 mx-auto rounded-lg" />
              ) : (
                <div>
                  <Upload className="h-12 w-12 mx-auto text-gray-400 mb-4" />
                  <p className="text-gray-600 dark:text-gray-400">Click to upload a face image</p>
                  <p className="text-sm text-gray-400 mt-1">JPG, PNG up to 10MB</p>
                </div>
              )}
              <input ref={fileRef} type="file" accept="image/*" multiple className="hidden" onChange={handleFileChange} />
            </div>
            {files.length > 0 && (
              <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                Selected: {files.length} image(s) - {files.map(f => f.name).join(', ')}
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
