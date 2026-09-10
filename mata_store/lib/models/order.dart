enum DeliveryType { pickup, courier, cdek, russianPost }
enum PaymentType { card, cash, sbp }
enum OrderStatus { pending, processing, shipped, delivered, cancelled }

class CheckoutData {
  final String name;
  final String phone;
  final String email;
  final DeliveryType deliveryType;
  final String? city;
  final String? street;
  final String? house;
  final String? apartment;
  final String? postalCode;
  final PaymentType paymentType;

  const CheckoutData({
    required this.name,
    required this.phone,
    required this.email,
    required this.deliveryType,
    this.city,
    this.street,
    this.house,
    this.apartment,
    this.postalCode,
    required this.paymentType,
  });

  Map<String, dynamic> toJson() => {
        'name': name,
        'phone': phone,
        'email': email,
        'deliveryType': deliveryType.name,
        'city': city,
        'street': street,
        'house': house,
        'apartment': apartment,
        'postalCode': postalCode,
        'paymentType': paymentType.name,
      };

  factory CheckoutData.fromJson(Map<String, dynamic> j) => CheckoutData(
        name: j['name'] as String,
        phone: j['phone'] as String,
        email: j['email'] as String,
        deliveryType: DeliveryType.values.firstWhere(
            (e) => e.name == j['deliveryType'],
            orElse: () => DeliveryType.courier),
        city: j['city'] as String?,
        street: j['street'] as String?,
        house: j['house'] as String?,
        apartment: j['apartment'] as String?,
        postalCode: j['postalCode'] as String?,
        paymentType: PaymentType.values.firstWhere(
            (e) => e.name == j['paymentType'],
            orElse: () => PaymentType.sbp),
      );
}

class OrderItem {
  final String productId;
  final String productName;
  final String productBrand;
  final String imageUrl;
  final double price;
  final String size;
  final String color;
  final int quantity;

  const OrderItem({
    required this.productId,
    required this.productName,
    required this.productBrand,
    required this.imageUrl,
    required this.price,
    required this.size,
    required this.color,
    required this.quantity,
  });

  double get total => price * quantity;

  Map<String, dynamic> toJson() => {
        'productId': productId,
        'productName': productName,
        'productBrand': productBrand,
        'imageUrl': imageUrl,
        'price': price,
        'size': size,
        'color': color,
        'quantity': quantity,
      };

  factory OrderItem.fromJson(Map<String, dynamic> j) => OrderItem(
        productId: j['productId'] as String,
        productName: j['productName'] as String,
        productBrand: j['productBrand'] as String,
        imageUrl: j['imageUrl'] as String,
        price: (j['price'] as num).toDouble(),
        size: j['size'] as String,
        color: j['color'] as String,
        quantity: j['quantity'] as int,
      );
}

class Order {
  final String id;
  final List<OrderItem> items;
  final double subtotal;
  final double deliveryCost;
  final int pointsRedeemed; // списано баллов (1 балл = 1 ₽), см. ECOSYSTEM_API
  final double total;
  final CheckoutData checkoutData;
  final OrderStatus status;
  final DateTime createdAt;

  const Order({
    required this.id,
    required this.items,
    required this.subtotal,
    required this.deliveryCost,
    this.pointsRedeemed = 0,
    required this.total,
    required this.checkoutData,
    required this.status,
    required this.createdAt,
  });

  String get shortId => id.split('-').last;

  Order copyWith({OrderStatus? status}) => Order(
        id: id,
        items: items,
        subtotal: subtotal,
        deliveryCost: deliveryCost,
        pointsRedeemed: pointsRedeemed,
        total: total,
        checkoutData: checkoutData,
        status: status ?? this.status,
        createdAt: createdAt,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'items': items.map((i) => i.toJson()).toList(),
        'subtotal': subtotal,
        'deliveryCost': deliveryCost,
        'pointsRedeemed': pointsRedeemed,
        'total': total,
        'checkoutData': checkoutData.toJson(),
        'status': status.name,
        'createdAt': createdAt.toIso8601String(),
      };

  factory Order.fromJson(Map<String, dynamic> j) => Order(
        id: j['id'] as String,
        items: (j['items'] as List)
            .map((i) => OrderItem.fromJson(i as Map<String, dynamic>))
            .toList(),
        subtotal: (j['subtotal'] as num).toDouble(),
        deliveryCost: (j['deliveryCost'] as num).toDouble(),
        pointsRedeemed: j['pointsRedeemed'] as int? ?? 0,
        total: (j['total'] as num).toDouble(),
        checkoutData: CheckoutData.fromJson(
            j['checkoutData'] as Map<String, dynamic>),
        status: OrderStatus.values.firstWhere(
            (e) => e.name == j['status'],
            orElse: () => OrderStatus.pending),
        createdAt: DateTime.parse(j['createdAt'] as String),
      );
}
