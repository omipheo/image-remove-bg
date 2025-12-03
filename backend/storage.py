"""Image storage management for processed images"""
# Store processed images temporarily (in production, use a proper storage solution)
processed_images = {}


def store_image(image_id, image_data, filename, format, mime_type):
    """Store a processed image"""
    processed_images[image_id] = {
        "data": image_data,
        "filename": filename,
        "format": format,
        "mime_type": mime_type
    }


def get_image(image_id):
    """Get a stored image by ID"""
    return processed_images.get(image_id)


def get_latest_image():
    """Get the most recently processed image"""
    if not processed_images:
        return None
    latest_id = list(processed_images.keys())[-1]
    return processed_images[latest_id]


def get_all_images():
    """Get all stored images (for debugging)"""
    return processed_images

