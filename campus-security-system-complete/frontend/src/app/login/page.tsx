'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/auth-context'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useToast } from '@/hooks/use-toast'
import { Eye, EyeOff, Shield, Camera, Lock } from 'lucide-react'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const { login, isAuthenticated, isLoading: authLoading } = useAuth()
  const { toast } = useToast()
  const router = useRouter()

  useEffect(() => {
    if (!authLoading && isAuthenticated) {
      router.replace('/dashboard')
    }
  }, [authLoading, isAuthenticated, router])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)

    try {
      await login(email, password)
      window.location.replace('/dashboard')
    } catch (error: any) {
      toast({
        title: "Login Failed",
        description: error.detail || "Invalid email or password",
        variant: "destructive",
      })
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-security-50 to-security-100 dark:from-gray-900 dark:to-gray-800 flex items-center justify-center p-4">
      <div className="w-full max-w-md space-y-8">
        {/* Header */}
        <div className="text-center">
          <img src="/iitb-logo.png" alt="IIT Bombay" className="mx-auto h-20 w-20 mb-4" />
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            IIT Bombay Security
          </h1>
          <p className="text-gray-600 dark:text-gray-400 mt-2">
            Facial Recognition System
          </p>
        </div>

        {/* Login Card */}
        <Card className="shadow-xl border-0 bg-white/80 backdrop-blur-sm dark:bg-gray-800/80">
          <CardHeader className="space-y-1">
            <CardTitle className="text-2xl font-semibold text-center">
              Sign In
            </CardTitle>
            <CardDescription className="text-center">
              Enter your credentials to access the security dashboard
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <Input
                type="email"
                placeholder="Email address"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={isLoading}
                leftIcon={<Lock className="h-4 w-4" />}
              />
              
              <Input
                type={showPassword ? 'text' : 'password'}
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={isLoading}
                leftIcon={<Lock className="h-4 w-4" />}
                rightIcon={
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="text-gray-400 hover:text-gray-600 focus:outline-none"
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                }
              />

              <Button
                type="submit"
                className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 disabled:opacity-40 disabled:cursor-not-allowed"
                loading={isLoading}
                disabled={!email || !password}
              >
                {isLoading ? 'Signing In...' : 'Sign In'}
              </Button>
            </form>

            {/* Demo Credentials */}
            <div className="mt-6 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
              <h3 className="text-sm font-medium text-blue-900 dark:text-blue-100 mb-2">
                Demo Credentials
              </h3>
              <div className="space-y-1 text-xs text-blue-700 dark:text-blue-300">
                <div>
                  <strong>Admin:</strong> admin@security.iitb.ac.in / admin123
                </div>
                <div>
                  <strong>Security Officer:</strong> security@security.iitb.ac.in / security123
                </div>
                <div>
                  <strong>Operator:</strong> operator@security.iitb.ac.in / operator123
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Features */}
        <div className="grid grid-cols-2 gap-4 text-center">
          <div className="bg-white/60 dark:bg-gray-800/60 backdrop-blur-sm rounded-lg p-4">
            <Camera className="h-6 w-6 text-security-600 mx-auto mb-2" />
            <p className="text-sm font-medium text-gray-900 dark:text-white">
              Real-time Monitoring
            </p>
            <p className="text-xs text-gray-600 dark:text-gray-400">
              CCTV & Drone Integration
            </p>
          </div>
          <div className="bg-white/60 dark:bg-gray-800/60 backdrop-blur-sm rounded-lg p-4">
            <Shield className="h-6 w-6 text-security-600 mx-auto mb-2" />
            <p className="text-sm font-medium text-gray-900 dark:text-white">
              AI-Powered Security
            </p>
            <p className="text-xs text-gray-600 dark:text-gray-400">
              Advanced Face Recognition
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="text-center text-xs text-gray-500 dark:text-gray-400">
          <p>© 2025 IIT Bombay Security System</p>
          <p className="mt-1">
            Powered by Advanced AI & Machine Learning
          </p>
        </div>
      </div>
    </div>
  )
}