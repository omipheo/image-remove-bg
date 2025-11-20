/**
 * Read image file as data URL
 */
export const readImageAsDataURL = (file) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (event) => resolve(event.target.result)
    reader.onerror = () => reject(new Error('Failed to read image file'))
    reader.readAsDataURL(file)
  })
}

/**
 * Download file from blob or data URL
 */
export const downloadFile = (blobOrUrl, filename) => {
  const link = document.createElement('a')
  link.href = typeof blobOrUrl === 'string' ? blobOrUrl : window.URL.createObjectURL(blobOrUrl)
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  
  if (typeof blobOrUrl !== 'string') {
    window.URL.revokeObjectURL(link.href)
  }
}

/**
 * Generate download filename
 */
export const generateDownloadFilename = (originalName, fileType) => {
  const nameWithoutExt = originalName.replace(/\.[^/.]+$/, '')
  const extension = fileType.toLowerCase() === 'jpeg' ? 'jpg' : 'png'
  return `${nameWithoutExt}-no-bg.${extension}`
}

/**
 * Filter image files from file list
 */
export const filterImageFiles = (files) => {
  return Array.from(files).filter(file => file.type.startsWith('image/'))
}

/**
 * Convert data URL to blob
 */
export const dataURLToBlob = (dataURL) => {
  const arr = dataURL.split(',')
  const mime = arr[0].match(/:(.*?);/)[1]
  const bstr = atob(arr[1])
  let n = bstr.length
  const u8arr = new Uint8Array(n)
  while (n--) {
    u8arr[n] = bstr.charCodeAt(n)
  }
  return new Blob([u8arr], { type: mime })
}

