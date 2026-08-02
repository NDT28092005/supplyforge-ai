export interface Product {
  id: string;
  userId: string;
  thirdPartyId: string;
  itemId?: string;
  productName: string;
  platform: string;
  itemSku: string;
  price: number;
  cost: number;
  stock: number;
  totalRevenue?: number;
  totalProfit?: number;
  totalOrders?: number;
  expirationDate?: string;
  activeOnWeb: boolean;
  createdAt: string;
  updatedAt: string;
}
