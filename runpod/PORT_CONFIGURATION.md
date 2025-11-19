# RunPod Port Configuration Guide

## How to Expose Port 8001 for HTTP Service

### Step 1: Access Pod Details

1. Go to your pod in RunPod console: [https://console.runpod.io/pods?id=5q4c0f92sj6do3](https://console.runpod.io/pods?id=5q4c0f92sj6do3)
2. Click on your pod name to open pod details

### Step 2: Expose HTTP Port

1. Go to the **"Details"** tab (not "Connect")
2. Look for one of these fields:
   - **"Expose HTTP Ports"**
   - **"HTTP Ports"**
   - **"Ports"** or **"Exposed Ports"**
3. Add port **8001** to the list
4. **Save** or **Apply** the changes
5. ⚠️ **Warning**: This will restart your pod! Save any work first.

### Step 3: Get HTTP Proxy URL

After the pod restarts, your HTTP proxy URL will be:

```
https://[POD_ID]-[PORT].proxy.runpod.net
```

**For your specific pod:**
- Pod ID: `5q4c0f92sj6do3`
- Port: `8001`
- **URL**: `https://5q4c0f92sj6do3-8001.proxy.runpod.net`

### Step 4: Verify

1. Go to **"Connect"** tab
2. Check **"HTTP Services"** section
3. You should see: `Port 8001 → Your Service` with a **Ready** status
4. The proxy URL should be displayed there

## Alternative: If You Can't Find the Setting

If you can't find the "Expose HTTP Ports" field:

1. **Check "Settings" or "Configuration" tab** - Some RunPod versions have it there
2. **Try editing the pod** - Look for an "Edit" or "Configure" button
3. **Check pod template settings** - Ports might be configured when deploying
4. **Use RunPod API** - Advanced users can use the API to configure ports

## Important Notes

- ⚠️ **HTTP proxy has 100-second timeout** - If processing takes longer, consider TCP port exposure
- ✅ **Service must bind to `0.0.0.0`** - Not `127.0.0.1` or `localhost`
- ✅ **Service must be running** - Start your `gpu_processor.py` before testing
- ✅ **Use HTTPS URL** - RunPod provides HTTPS automatically

## Testing the URL

Once you have the URL, test it:

```bash
# Health check
curl https://5q4c0f92sj6do3-8001.proxy.runpod.net/health

# Should return:
# {"status": "healthy", "service": "gpu-processor"}
```

## Troubleshooting

**URL not working?**
- Ensure pod is running
- Check service is listening on port 8001: `netstat -tulpn | grep 8001`
- Verify service binds to `0.0.0.0`, not `127.0.0.1`
- Check pod logs for errors

**Can't find port setting?**
- Try different tabs: Details, Settings, Configuration
- Check if you need to "Edit" the pod first
- Some templates pre-configure ports - check template settings

## References

- [RunPod Port Exposure Documentation](https://docs.runpod.io/pods/configuration/expose-ports)
- [RunPod HTTP Services Guide](https://docs.runpod.io/docs/hosting-http-services)

