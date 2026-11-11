import type { AuthMe, Customer, CustomerProfile, Dashboard, Item, ItemStatus, PaymentEvidence, Shipment } from '../types'
const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'
export class ApiError extends Error { constructor(public status:number, message:string) { super(message) } }
const fieldLabels:Record<string,string>={display_name:'ФИО',phone:'Телефон',country_code:'Страна',postal_code:'Индекс',region:'Регион',city:'Город',address_line1:'Улица, дом, квартира',address_line2:'Дополнение к адресу',reason:'Причина'}
async function request<T>(path:string, initData:string, options:RequestInit={}): Promise<T> {
  const headers=new Headers(options.headers)
  headers.set('X-Telegram-Init-Data',initData)
  if(!(options.body instanceof FormData))headers.set('Content-Type','application/json')
  const response = await fetch(`${baseUrl}${path}`, {...options,headers})
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try { const body = await response.json(); if(typeof body.detail==='string')message=body.detail;else if(Array.isArray(body.detail))message=body.detail.map((issue:{loc?:unknown[];msg?:string})=>{const field=String(issue.loc?.at(-1)??'Поле');return `${fieldLabels[field]??field}: ${issue.msg??'проверьте значение'}`}).join('\n') } catch { /* not JSON */ }
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}
export const api = {
  me:(data:string)=>request<AuthMe>('/auth/me',data), dashboard:(data:string)=>request<Dashboard>('/dashboard',data),
  items:(data:string)=>request<Item[]>('/items',data), customers:(data:string)=>request<Customer[]>('/admin/customers',data),
  warehouse:(data:string)=>request<Item[]>('/admin/warehouse',data),
  shipments:(data:string)=>request<Shipment[]>('/shipments',data),
  createShipment:(data:string,customerId:string,itemIds:string[],carrier:string,trackingNumber:string)=>request<Shipment>(`/admin/customers/${customerId}/shipments`,data,{method:'POST',body:JSON.stringify({item_ids:itemIds,carrier,tracking_number:trackingNumber})}),
  saveItemTracking:(data:string,itemId:string,carrier:string,trackingNumber:string)=>request<Shipment>(`/admin/items/${itemId}/tracking`,data,{method:'PUT',body:JSON.stringify({carrier,tracking_number:trackingNumber})}),
  updateItemStatus:(data:string,id:string,status:ItemStatus)=>request<Item>(`/admin/items/${id}/status`,data,{method:'PATCH',body:JSON.stringify({status})}),
  correctItemStatus:(data:string,id:string,status:ItemStatus,reason:string)=>request<Item>(`/admin/items/${id}/status-correction`,data,{method:'PATCH',body:JSON.stringify({status,reason})}),
  profile:(data:string)=>request<CustomerProfile>('/profile',data),
  saveProfile:(data:string,profile:Omit<CustomerProfile,'complete'>)=>request<CustomerProfile>('/profile',data,{method:'PUT',body:JSON.stringify(profile)}),
  paymentEvidence:(data:string)=>request<PaymentEvidence[]>('/admin/payment-evidence',data),
  addPaymentEvidence:(data:string,itemId:string,note:string,file:File|null)=>{const body=new FormData();if(note.trim())body.append('note',note.trim());if(file)body.append('image',file);return request<PaymentEvidence>(`/admin/items/${itemId}/payment-evidence`,data,{method:'POST',body})},
  paymentEvidenceImage:async(data:string,evidenceId:string)=>{const response=await fetch(`${baseUrl}/admin/payment-evidence/${evidenceId}/image`,{headers:{'X-Telegram-Init-Data':data}});if(!response.ok)throw new ApiError(response.status,'Не удалось открыть изображение');return URL.createObjectURL(await response.blob())},
}
